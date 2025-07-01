from __future__ import annotations
import json
import asyncpg
from typing import Optional, Sequence

from optimed.core.domain import DICOMImage, ImageStatus, ImageModalityType, DICOMMetadata, ImageDimensions, WindowLevel
from optimed.core.ports import ImageRepository
from optimed.adapters.database.pool_manager import get_shared_pool

class PostgreSQLImageRepository(ImageRepository):
    """PostgreSQL implementation of ImageRepository using shared connection pool."""
    
    def __init__(self, dsn: str):
        self._connection_string = dsn
        self._tables_created = False

    async def _get_pool(self) -> asyncpg.Pool:
        """Get the shared connection pool."""
        pool = await get_shared_pool(self._connection_string)
        
        if not self._tables_created:
            await self._ensure_tables_once(pool)
            self._tables_created = True
        
        return pool

    async def _ensure_tables_once(self, pool: asyncpg.Pool):
        """Create tables once, safely with better error handling."""
        try:
            async with pool.acquire() as conn:
                # Check if table exists first
                table_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'dicom_images'
                    );
                """)
                
                if not table_exists:
                    print("[DB] Creating dicom_images table...")
                    await conn.execute("""
                        CREATE TABLE dicom_images (
                            image_id TEXT PRIMARY KEY,
                            patient_id TEXT,
                            user_id TEXT NOT NULL,
                            filename TEXT NOT NULL,
                            file_size BIGINT NOT NULL,
                            metadata_json JSONB NOT NULL,
                            dimensions_json JSONB NOT NULL,
                            window_level_json JSONB NOT NULL,
                            status TEXT NOT NULL,
                            uploaded_at TIMESTAMP WITH TIME ZONE NOT NULL,
                            processed_at TIMESTAMP WITH TIME ZONE,
                            storage_path TEXT,
                            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                        )
                    """)
                    
                    # Create indexes
                    await conn.execute("CREATE INDEX IF NOT EXISTS idx_dicom_images_user_id ON dicom_images(user_id)")
                    await conn.execute("CREATE INDEX IF NOT EXISTS idx_dicom_images_patient_id ON dicom_images(patient_id)")
                    await conn.execute("CREATE INDEX IF NOT EXISTS idx_dicom_images_status ON dicom_images(status)")
                    await conn.execute("CREATE INDEX IF NOT EXISTS idx_dicom_images_uploaded_at ON dicom_images(uploaded_at)")
                    
                    print("[DB] ✅ dicom_images table created successfully")
                else:
                    print("[DB] dicom_images table already exists")
                    
        except Exception as e:
            print(f"[ERROR] Failed to create dicom_images table: {e}")
            # Don't raise here, let the app continue

    async def save_image(self, image: DICOMImage) -> None:
        """Save a DICOM image record with better error handling."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            try:
                await conn.execute("""
                    INSERT INTO dicom_images (
                        image_id, patient_id, user_id, filename, file_size,
                        metadata_json, dimensions_json, window_level_json,
                        status, uploaded_at, processed_at, storage_path
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                """,
                    image.image_id,
                    image.patient_id,
                    image.user_id,
                    image.filename,
                    image.file_size,
                    json.dumps(self._metadata_to_dict(image.metadata)),
                    json.dumps(self._dimensions_to_dict(image.dimensions)),
                    json.dumps(self._window_level_to_dict(image.default_window_level)),
                    image.status.value,
                    image.uploaded_at,
                    image.processed_at,
                    image.storage_path
                )
                print(f"[DB] ✅ Saved image {image.image_id}")
            except Exception as e:
                print(f"[ERROR] Failed to save image {image.image_id}: {e}")
                raise

    async def get_image_by_id(self, image_id: str) -> Optional[DICOMImage]:
        """Retrieve a DICOM image by ID."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT image_id, patient_id, user_id, filename, file_size,
                       metadata_json, dimensions_json, window_level_json,
                       status, uploaded_at, processed_at, storage_path
                FROM dicom_images 
                WHERE image_id = $1
            """, image_id)
            
            if row:
                return self._row_to_domain(row)
            return None

    async def get_images_by_user(self, user_id: str) -> Sequence[DICOMImage]:
        """Get all images uploaded by a user with better error handling."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            try:
                rows = await conn.fetch("""
                    SELECT image_id, patient_id, user_id, filename, file_size,
                           metadata_json, dimensions_json, window_level_json,
                           status, uploaded_at, processed_at, storage_path
                    FROM dicom_images 
                    WHERE user_id = $1
                    ORDER BY uploaded_at DESC
                """, user_id)
                
                result = []
                for row in rows:
                    try:
                        domain_obj = self._row_to_domain(row)
                        result.append(domain_obj)
                    except Exception as e:
                        print(f"[ERROR] Failed to convert row to domain object: {e}")
                        print(f"[DEBUG] Row data: {dict(row)}")
                        # Skip this row and continue with others
                        continue
                        
                print(f"[DB] ✅ Retrieved {len(result)} images for user {user_id}")
                return result
                
            except Exception as e:
                print(f"[ERROR] Failed to get images for user {user_id}: {e}")
                raise

    async def get_images_by_patient(self, patient_id: str) -> Sequence[DICOMImage]:
        """Get all images for a specific patient."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT image_id, patient_id, user_id, filename, file_size,
                       metadata_json, dimensions_json, window_level_json,
                       status, uploaded_at, processed_at, storage_path
                FROM dicom_images 
                WHERE patient_id = $1
                ORDER BY uploaded_at DESC
            """, patient_id)
            
            return [self._row_to_domain(row) for row in rows]

    async def update_image(self, image: DICOMImage) -> None:
        """Update an existing image record."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE dicom_images SET
                    patient_id = $2, user_id = $3, filename = $4, file_size = $5,
                    metadata_json = $6, dimensions_json = $7, window_level_json = $8,
                    status = $9, uploaded_at = $10, processed_at = $11, storage_path = $12,
                    updated_at = NOW()
                WHERE image_id = $1
            """,
                image.image_id,
                image.patient_id,
                image.user_id,
                image.filename,
                image.file_size,
                json.dumps(self._metadata_to_dict(image.metadata)),
                json.dumps(self._dimensions_to_dict(image.dimensions)),
                json.dumps(self._window_level_to_dict(image.default_window_level)),
                image.status.value,
                image.uploaded_at,
                image.processed_at,
                image.storage_path
            )

    async def delete_image(self, image_id: str) -> None:
        """Delete a DICOM image."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM dicom_images WHERE image_id = $1
            """, image_id)
    
    def _row_to_domain(self, row) -> DICOMImage:
        """Convert database row to DICOMImage domain object."""
        # Parse JSON fields - handle case where they might already be parsed
        metadata_dict = row['metadata_json']
        if isinstance(metadata_dict, str):
            metadata_dict = json.loads(metadata_dict)
        
        dimensions_dict = row['dimensions_json']
        if isinstance(dimensions_dict, str):
            dimensions_dict = json.loads(dimensions_dict)
        
        window_level_dict = row['window_level_json']
        if isinstance(window_level_dict, str):
            window_level_dict = json.loads(window_level_dict)
        
        # Reconstruct metadata
        metadata = DICOMMetadata(
            patient_name=metadata_dict.get('patient_name'),
            patient_id=metadata_dict.get('patient_id'),
            study_date=metadata_dict.get('study_date'),
            study_time=metadata_dict.get('study_time'),
            modality=ImageModalityType(metadata_dict['modality']) if metadata_dict.get('modality') else None,
            series_description=metadata_dict.get('series_description'),
            study_description=metadata_dict.get('study_description'),
            body_part_examined=metadata_dict.get('body_part_examined'),
            slice_thickness=metadata_dict.get('slice_thickness'),
            pixel_spacing=metadata_dict.get('pixel_spacing'),
            image_position=metadata_dict.get('image_position'),
            image_orientation=metadata_dict.get('image_orientation'),
            window_center=metadata_dict.get('window_center'),
            window_width=metadata_dict.get('window_width'),
            rows=metadata_dict.get('rows'),
            columns=metadata_dict.get('columns'),
            bits_allocated=metadata_dict.get('bits_allocated'),
            bits_stored=metadata_dict.get('bits_stored'),
        )
        
        # Reconstruct dimensions
        dimensions = ImageDimensions(
            width=dimensions_dict['width'],
            height=dimensions_dict['height'],
            depth=dimensions_dict.get('depth'),
            pixel_spacing_x=dimensions_dict.get('pixel_spacing_x'),
            pixel_spacing_y=dimensions_dict.get('pixel_spacing_y'),
            slice_thickness=dimensions_dict.get('slice_thickness')
        )
        
        # Reconstruct window level
        window_level = WindowLevel(
            center=window_level_dict['center'],
            width=window_level_dict['width']
        )
        
        return DICOMImage(
            image_id=row['image_id'],
            patient_id=row['patient_id'],
            user_id=row['user_id'],
            filename=row['filename'],
            file_size=row['file_size'],
            metadata=metadata,
            dimensions=dimensions,
            default_window_level=window_level,
            status=ImageStatus(row['status']),
            uploaded_at=row['uploaded_at'],
            processed_at=row['processed_at'],
            storage_path=row['storage_path']
        )

    def _metadata_to_dict(self, metadata: DICOMMetadata) -> dict:
        """Convert metadata to dictionary for JSON storage."""
        return {
            'patient_name': metadata.patient_name,
            'patient_id': metadata.patient_id,
            'study_date': metadata.study_date,
            'study_time': metadata.study_time,
            'modality': metadata.modality.value if metadata.modality else None,
            'series_description': metadata.series_description,
            'study_description': metadata.study_description,
            'body_part_examined': metadata.body_part_examined,
            'slice_thickness': metadata.slice_thickness,
            'pixel_spacing': metadata.pixel_spacing,
            'image_position': metadata.image_position,
            'image_orientation': metadata.image_orientation,
            'window_center': metadata.window_center,
            'window_width': metadata.window_width,
            'rows': metadata.rows,
            'columns': metadata.columns,
            'bits_allocated': metadata.bits_allocated,
            'bits_stored': metadata.bits_stored,
        }

    def _dimensions_to_dict(self, dimensions: ImageDimensions) -> dict:
        """Convert dimensions to dictionary for JSON storage."""
        return {
            'width': dimensions.width,
            'height': dimensions.height,
            'depth': dimensions.depth,
            'pixel_spacing_x': dimensions.pixel_spacing_x,
            'pixel_spacing_y': dimensions.pixel_spacing_y,
            'slice_thickness': dimensions.slice_thickness
        }

    def _window_level_to_dict(self, window_level: WindowLevel) -> dict:
        """Convert window level to dictionary for JSON storage."""
        return {
            'center': window_level.center,
            'width': window_level.width
        }