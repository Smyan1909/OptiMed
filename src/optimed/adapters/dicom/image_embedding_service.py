import numpy as np
from typing import Sequence
from optimed.core.domain import ImagePixelData, DICOMMetadata
from optimed.core.ports import ImageEmbeddingService
import torch
from transformers import AutoImageProcessor, AutoModel
from PIL import Image
from optimed.core.logging_utils import get_logger, log_error

logger = get_logger(__name__)


class DICOMImageEmbeddingService(ImageEmbeddingService):
    """Creates embeddings from DICOM images using pre-trained vision models."""
    
    def __init__(self, model_name: str = "microsoft/swin-base-patch4-window7-224"):
        # Initialize vision model for image embeddings
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.image_processor = AutoImageProcessor.from_pretrained(model_name)
        self.vision_model = AutoModel.from_pretrained(model_name)
        self.vision_model.to(self.device)
        self.vision_model.eval()

        logger.info(f"Initialized DICOM embedding service with model: {model_name} on device: {self.device}")
    
    async def create_image_embedding(self, pixel_data: ImagePixelData) -> Sequence[float]:
        """Create vector embedding from DICOM pixel data using pre-trained vision model."""
        try:
            # Convert pixel array to PIL Image
            pixel_array = pixel_data.pixel_array
            
            # Handle 3D volumes by taking middle slice
            if len(pixel_array.shape) == 3:
                pixel_array = pixel_array[pixel_array.shape[0] // 2]
            
            # Normalize to 0-255 range
            if pixel_array.dtype != np.uint8:
                pixel_min, pixel_max = pixel_array.min(), pixel_array.max()
                if pixel_max > pixel_min:
                    pixel_array = ((pixel_array - pixel_min) / (pixel_max - pixel_min) * 255).astype(np.uint8)
                else:
                    pixel_array = np.zeros_like(pixel_array, dtype=np.uint8)
            
            # Convert grayscale to RGB (vision models expect 3 channels)
            if len(pixel_array.shape) == 2:
                pixel_array = np.stack([pixel_array] * 3, axis=-1)
            
            # Create PIL Image
            image = Image.fromarray(pixel_array, mode='RGB')
            
            # Process image with the pre-trained processor
            inputs = self.image_processor(images=image, return_tensors="pt")
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            
            # Generate embeddings
            with torch.no_grad():
                outputs = self.vision_model(**inputs)
                
                # Extract features (different models have different output structures)
                if hasattr(outputs, 'pooler_output') and outputs.pooler_output is not None:
                    # For models like BERT-style vision transformers
                    embedding = outputs.pooler_output
                elif hasattr(outputs, 'last_hidden_state'):
                    # For models with sequence outputs, take mean
                    embedding = outputs.last_hidden_state.mean(dim=1)
                else:
                    # Fallback: use the first element if outputs is a tuple/BaseModelOutput
                    if hasattr(outputs, 'keys'):
                        # If it's a dict-like object, try to get a reasonable feature
                        for key in ['pooler_output', 'last_hidden_state', 'hidden_states']:
                            if hasattr(outputs, key):
                                feat = getattr(outputs, key)
                                if feat is not None:
                                    embedding = feat.mean(dim=1) if len(feat.shape) > 2 else feat
                                    break
                        else:
                            # Ultimate fallback
                            embedding = torch.mean(torch.stack([v for v in outputs.values() if isinstance(v, torch.Tensor)]), dim=0)
                    else:
                        embedding = outputs[0].mean(dim=1) if isinstance(outputs, tuple) else outputs.mean(dim=1)
                
                # Convert to CPU and flatten
                embedding = embedding.cpu().numpy().flatten()
            
            # Normalize embedding to unit vector for better similarity search
            embedding_norm = np.linalg.norm(embedding)
            if embedding_norm > 0:
                embedding = embedding / embedding_norm
            
            # Pad or truncate to 768 dimensions for consistency
            target_size = 768
            if len(embedding) < target_size:
                embedding = np.pad(embedding, (0, target_size - len(embedding)))
            else:
                embedding = embedding[:target_size]
            
            return embedding.tolist()

        except Exception as e:
            log_error(logger, "create_image_embedding", e)
            # Return zero embedding on error
            return [0.0] * 768
    
    async def create_metadata_embedding(self, metadata: DICOMMetadata) -> Sequence[float]:
        """Create simple metadata embedding using text representation."""
        try:
            # Create text representation of metadata
            metadata_text = self._metadata_to_text(metadata)
            
            if not metadata_text.strip():
                # Return zero embedding if no metadata
                return [0.0] * 768
            
            # Simple character-based embedding
            text_bytes = metadata_text.encode('utf-8')
            
            # Fix: Check if text_bytes is empty
            if len(text_bytes) == 0:
                return [0.0] * 768
            
            # Create a simple embedding based on text characteristics
            embedding = np.zeros(768, dtype=np.float32)
            
            # Use text length and character frequencies
            embedding[0] = min(len(text_bytes) / 100.0, 1.0)  # Normalized length
            
            # Character frequency features - fix the array depth issue
            try:
                # Convert to numpy array first to ensure proper handling
                text_array = np.frombuffer(text_bytes, dtype=np.uint8)
                
                # Only proceed if we have data
                if len(text_array) > 0:
                    char_counts = np.bincount(text_array, minlength=256)
                    char_counts = char_counts.astype(np.float32)
                    
                    # Normalize
                    char_features = char_counts / len(text_array)
                    
                    # Ensure we don't exceed array bounds
                    feature_len = min(len(char_features), 767)
                    if feature_len > 0:
                        embedding[1:feature_len+1] = char_features[:feature_len]

            except Exception:
                logger.warning("Character frequency extraction failed for metadata embedding, using length feature only")
                # Just use length feature if character analysis fails
                pass
            
            return embedding.tolist()

        except Exception as e:
            log_error(logger, "create_metadata_embedding", e)
            # Return zero embedding on error
            return [0.0] * 768
    
    def _metadata_to_text(self, metadata: DICOMMetadata) -> str:
        """Convert DICOM metadata to searchable text."""
        text_parts = []
        
        if metadata.modality:
            text_parts.append(metadata.modality.value)
        if metadata.body_part_examined:
            text_parts.append(metadata.body_part_examined)
        if metadata.study_description:
            text_parts.append(metadata.study_description)
        if metadata.series_description:
            text_parts.append(metadata.series_description)
        if metadata.patient_name:
            text_parts.append(f"patient {metadata.patient_name}")
        
        return " ".join(text_parts).lower()