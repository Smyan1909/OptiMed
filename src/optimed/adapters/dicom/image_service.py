import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence, Any

from optimed.core.domain import (
    DICOMImage,
    WindowLevel,
    ImagePixelData,
    ImageUploadRequest,
    ImageStatus,
)

from optimed.core.ports import (
    ImageRepository,
    ImageStorage,
    DICOMProcessor,
    ImageService,
    VectorStore,
    ImageEmbeddingService, 
)


class ImageServiceImpl(ImageService):
    """Implementation of image service using hexagonal architecture."""
    
    def __init__(
        self,
        image_repository: ImageRepository,
        image_storage: ImageStorage,
        dicom_processor: DICOMProcessor,
        embedding_service: Optional[ImageEmbeddingService] = None,
        vector_store: Optional[VectorStore] = None
    ):
        self._image_repository = image_repository
        self._image_storage = image_storage
        self._dicom_processor = dicom_processor
        self._embedding_service = embedding_service
        self._vector_store = vector_store
    
    async def upload_image(self, request: ImageUploadRequest) -> DICOMImage:
        """Upload and process a DICOM image."""
        # Validate request
        request.validate_request()
        
        # Validate DICOM file
        is_valid = await self._dicom_processor.validate_dicom_file(request.file_content)
        if not is_valid:
            raise ValueError("Invalid DICOM file")
        
        # Generate unique image ID
        image_id = f"img_{uuid.uuid4()}"
        
        # Extract metadata and properties
        metadata = await self._dicom_processor.extract_metadata(request.file_content)
        dimensions = await self._dicom_processor.get_image_dimensions(request.file_content)
        default_window_level = await self._dicom_processor.get_default_window_level(request.file_content)
        
        # Create image domain object
        image = DICOMImage(
            image_id=image_id,
            patient_id=request.patient_id or metadata.patient_id,
            user_id=request.user_id,
            filename=request.filename,
            file_size=len(request.file_content),
            metadata=metadata,
            dimensions=dimensions,
            default_window_level=default_window_level,
            status=ImageStatus.PROCESSING,
            uploaded_at=datetime.now(timezone.utc)
        )
        
        # Store the image record
        await self._image_repository.save_image(image)
        
        try:
            # Store the raw file
            storage_path = await self._image_storage.store_image_file(image_id, request.file_content)
            
            # Extract and store pixel data (pass image_id to processor)
            pixel_data = await self._dicom_processor.extract_pixel_data(request.file_content, image_id)
            await self._image_storage.store_pixel_data(pixel_data)
            
            if self._embedding_service and self._vector_store:
                await self._create_and_store_embeddings(image, pixel_data)

            # Update image with storage path and ready status
            updated_image = DICOMImage(
                image_id=image.image_id,
                patient_id=image.patient_id,
                user_id=image.user_id,
                filename=image.filename,
                file_size=image.file_size,
                metadata=image.metadata,
                dimensions=image.dimensions,
                default_window_level=image.default_window_level,
                status=ImageStatus.READY,
                uploaded_at=image.uploaded_at,
                processed_at=datetime.now(timezone.utc),
                storage_path=storage_path
            )
            
            await self._image_repository.update_image(updated_image)
            return updated_image
            
        except Exception as e:
            # Update status to error
            error_image = DICOMImage(
                image_id=image.image_id,
                patient_id=image.patient_id,
                user_id=image.user_id,
                filename=image.filename,
                file_size=image.file_size,
                metadata=image.metadata,
                dimensions=image.dimensions,
                default_window_level=image.default_window_level,
                status=ImageStatus.ERROR,
                uploaded_at=image.uploaded_at,
                processed_at=datetime.now(timezone.utc),
                storage_path=image.storage_path
            )
            await self._image_repository.update_image(error_image)
            raise e
    
    async def get_image(self, image_id: str, user_id: str) -> Optional[DICOMImage]:
        """Get image details with access control."""
        image = await self._image_repository.get_image_by_id(image_id)
        
        # Basic access control - users can only access their own images
        # TODO: Implement more sophisticated access control based on roles/permissions
        if image and image.user_id == user_id:
            return image
        
        return None
    
    async def get_image_pixel_data(
        self, 
        image_id: str, 
        user_id: str,
        window_level: Optional[WindowLevel] = None
    ) -> Optional[ImagePixelData]:
        """Get image pixel data with optional windowing."""
        # Check access
        image = await self.get_image(image_id, user_id)
        if not image or not image.is_ready():
            return None
        
        # Get pixel data
        pixel_data = await self._image_storage.get_pixel_data(image_id)
        if not pixel_data:
            return None
        
        # Apply windowing if requested
        if window_level:
            # Create a new pixel data object with windowed array
            windowed_array = pixel_data.get_normalized_array(window_level)
            return ImagePixelData(
                image_id=pixel_data.image_id,
                pixel_array=windowed_array,
                original_dtype="uint8",  # Normalized to uint8
                photometric_interpretation=pixel_data.photometric_interpretation
            )
        
        return pixel_data
    
    async def list_user_images(self, user_id: str) -> Sequence[DICOMImage]:
        """Sequence all images for a user."""
        return await self._image_repository.get_images_by_user(user_id)
    
    async def list_patient_images(self, patient_id: str, user_id: str) -> Sequence[DICOMImage]:
        """Sequence all images for a patient with access control."""
        # Get all images for the patient
        images = await self._image_repository.get_images_by_patient(patient_id)
        
        # Filter based on user access (simplified - in production, implement proper ACL)
        # For now, users can see images they uploaded or all if they have appropriate role
        accessible_images = [img for img in images if img.user_id == user_id]
        
        return accessible_images
    
    async def delete_image(self, image_id: str, user_id: str) -> None:
        """Delete an image with access control."""
        # Check access
        image = await self.get_image(image_id, user_id)
        if not image:
            raise ValueError("Image not found or access denied")
        
        # Delete from storage
        await self._image_storage.delete_image_file(image_id)
        
        # Delete from repository
        await self._image_repository.delete_image(image_id)

    async def _create_and_store_embeddings(self, image: DICOMImage, pixel_data: ImagePixelData) -> None:
        """Create and store embeddings for the DICOM image."""
        try:
            # Create image embedding
            if self._embedding_service is not None and self._vector_store is not None:
                image_embedding = await self._embedding_service.create_image_embedding(pixel_data)
                
                # Create metadata embedding
                metadata_embedding = await self._embedding_service.create_metadata_embedding(image.metadata)
                
                # Combine embeddings (simple average)
                combined_embedding = [
                    (img + meta) / 2 for img, meta in zip(image_embedding, metadata_embedding)
                ]
                
                # Store in vector database
                embedding_metadata = {
                    'type': 'dicom',
                    'image_id': image.image_id,
                    'patient_id': image.patient_id,
                    'user_id': image.user_id,
                    'modality': image.metadata.modality.value if image.metadata.modality else None,
                    'body_part': image.metadata.body_part_examined,
                    'study_description': image.metadata.study_description,
                    'filename': image.filename,
                    'uploaded_at': image.uploaded_at.isoformat()
                }
                
                await self._vector_store.store_dicom_embedding(
                    image.image_id,
                    combined_embedding,
                    embedding_metadata
                )
            
        except Exception as e:
            print(f"Warning: Failed to create embeddings for image {image.image_id}: {e}")
            # Don't fail the upload if embedding creation fails
    
    async def find_similar_images(self, image_id: str, user_id: str, limit: int = 5) -> list[dict[str, Any]]:
        """Find similar DICOM images based on embeddings."""
        if not self._embedding_service or not self._vector_store:
            return []
        
        try:
            # Get the reference image
            image = await self.get_image(image_id, user_id)
            if not image:
                return []
            
            # Get pixel data
            pixel_data = await self._image_storage.get_pixel_data(image_id)
            if not pixel_data:
                return []
            
            # Create query embedding
            image_embedding = await self._embedding_service.create_image_embedding(pixel_data)
            metadata_embedding = await self._embedding_service.create_metadata_embedding(image.metadata)
            
            combined_embedding = [
                (img + meta) / 2 for img, meta in zip(image_embedding, metadata_embedding)
            ]
            
            # Search for similar images
            similar_images = await self._vector_store.search_similar_dicom(
                combined_embedding, 
                limit=limit + 1  # +1 to exclude the query image itself
            )
            
            # Filter out the query image and user access control
            filtered_results = []
            for result in similar_images:
                if (result['metadata']['image_id'] != image_id and 
                    result['metadata']['user_id'] == user_id):
                    filtered_results.append(result)
            
            return filtered_results[:limit]
            
        except Exception as e:
            print(f"Error finding similar images: {e}")
            return []