import pickle
import aiofiles
from pathlib import Path
from typing import Optional

from optimed.core.domain import ImagePixelData
from optimed.core.ports import ImageStorage


class FileSystemImageStorage(ImageStorage):
    """File system implementation of ImageStorage."""
    
    def __init__(self, base_storage_path: str = "data/images"):
        self.base_path = Path(base_storage_path)
        self.dicom_path = self.base_path / "dicom"
        self.pixel_data_path = self.base_path / "pixel_data"
        
        # Create directories if they don't exist
        self.dicom_path.mkdir(parents=True, exist_ok=True)
        self.pixel_data_path.mkdir(parents=True, exist_ok=True)
    
    async def store_image_file(self, image_id: str, file_content: bytes) -> str:
        """Store raw DICOM file and return storage path."""
        file_path = self.dicom_path / f"{image_id}.dcm"
        
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(file_content)
        
        return str(file_path)
    
    async def get_image_file(self, storage_path: str) -> bytes:
        """Retrieve raw DICOM file content."""
        async with aiofiles.open(storage_path, 'rb') as f:
            return await f.read()
    
    async def store_pixel_data(self, pixel_data: ImagePixelData) -> None:
        """Store processed pixel data for fast access."""
        file_path = self.pixel_data_path / f"{pixel_data.image_id}.pkl"
        
        # Serialize pixel data using pickle
        data_to_store = {
            'image_id': pixel_data.image_id,
            'pixel_array': pixel_data.pixel_array,
            'original_dtype': pixel_data.original_dtype,
            'photometric_interpretation': pixel_data.photometric_interpretation
        }
        
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(pickle.dumps(data_to_store))
    
    async def get_pixel_data(self, image_id: str) -> Optional[ImagePixelData]:
        """Retrieve processed pixel data."""
        file_path = self.pixel_data_path / f"{image_id}.pkl"
        
        if not file_path.exists():
            return None
        
        try:
            async with aiofiles.open(file_path, 'rb') as f:
                content = await f.read()
                data = pickle.loads(content)
            
            return ImagePixelData(
                image_id=data['image_id'],
                pixel_array=data['pixel_array'],
                original_dtype=data['original_dtype'],
                photometric_interpretation=data['photometric_interpretation']
            )
        except Exception:
            return None
    
    async def delete_image_files(self, image_id: str) -> None:
        """Delete all files associated with an image."""
        # Delete DICOM file
        dicom_file = self.dicom_path / f"{image_id}.dcm"
        if dicom_file.exists():
            dicom_file.unlink()
        
        # Delete pixel data file
        pixel_file = self.pixel_data_path / f"{image_id}.pkl"
        if pixel_file.exists():
            pixel_file.unlink()