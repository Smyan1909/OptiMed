from __future__ import annotations
from .mixins import FrozenModel
from .enums import ImageModalityType, ImageStatus, GeneratedImagePurpose
from .clinical import PatientContext
from typing import Optional, Dict, List, Any 
from datetime import datetime
from pydantic import field_validator, Field
import uuid
import numpy as np 


class DICOMMetadata(FrozenModel):
    """DICOM metadata extracted from the file."""
    patient_name: Optional[str] = None
    patient_id: Optional[str] = None
    study_date: Optional[str] = None
    study_time: Optional[str] = None
    modality: Optional[ImageModalityType] = None
    series_description: Optional[str] = None
    study_description: Optional[str] = None
    body_part_examined: Optional[str] = None
    slice_thickness: Optional[float] = None
    pixel_spacing: Optional[List[float]] = None
    image_position: Optional[List[float]] = None
    image_orientation: Optional[List[float]] = None
    window_center: Optional[float] = None
    window_width: Optional[float] = None
    rows: Optional[int] = None
    columns: Optional[int] = None
    bits_allocated: Optional[int] = None
    bits_stored: Optional[int] = None
    
    def to_dict(self) -> Dict[str, str]:
        """Convert metadata to dictionary for serialization."""
        result = {}
        for key, value in self.__dict__.items():
            if value is not None:
                if isinstance(value, ImageModalityType):
                    result[key.replace('_', ' ').title()] = value.value
                elif isinstance(value, list):
                    result[key.replace('_', ' ').title()] = str(value)
                else:
                    result[key.replace('_', ' ').title()] = str(value)
        return result


class ImageDimensions(FrozenModel):
    """Image dimensional information."""
    width: int
    height: int
    depth: Optional[int] = None  # For 3D volumes
    pixel_spacing_x: Optional[float] = None  # mm per pixel
    pixel_spacing_y: Optional[float] = None  # mm per pixel
    slice_thickness: Optional[float] = None  # mm


class WindowLevel(FrozenModel):
    """Window/Level settings for image display."""
    center: float
    width: float
    
    @classmethod
    def default(cls) -> WindowLevel:
        """Default window/level for general purpose viewing."""
        return cls(center=128, width=256)
    
class DICOMImage(FrozenModel):
    """Domain model for a DICOM medical image."""
    image_id: str
    # patient_id removed for GDPR compliance
    user_id: str  # User who uploaded the image
    filename: str
    file_size: int  # Size in bytes
    
    # Image properties
    metadata: DICOMMetadata
    dimensions: ImageDimensions
    default_window_level: WindowLevel
    
    # Tracking
    status: ImageStatus
    uploaded_at: datetime
    processed_at: Optional[datetime] = None
    
    # File storage reference
    storage_path: Optional[str] = None

    def is_ready(self) -> bool:
        """Check if image is ready for viewing."""
        return self.status == ImageStatus.READY
    
    def is_3d_volume(self) -> bool:
        """Check if this is a 3D volume dataset."""
        return self.dimensions.depth is not None and self.dimensions.depth > 1
    
    def get_display_name(self) -> str:
        """Get a human-readable display name for the image."""
        if self.metadata.series_description:
            return self.metadata.series_description
        elif self.metadata.study_description:
            return self.metadata.study_description
        elif self.metadata.modality:
            return f"{self.metadata.modality.value} Image"
        else:
            return self.filename
        
class ImagePixelData(FrozenModel):
    """Raw pixel data for a DICOM image."""
    model_config = {'arbitrary_types_allowed': True}

    image_id: str
    pixel_array: np.ndarray  # Raw pixel data
    original_dtype: str  # Original data type
    photometric_interpretation: Optional[str] = None
    
    @field_validator('pixel_array')
    @classmethod
    def validate_pixel_array(cls, v):
        """Validate that pixel_array is a numpy array."""
        if not isinstance(v, np.ndarray):
            raise ValueError('pixel_array must be a numpy ndarray')
        return v
    
    def get_normalized_array(self, window_level: Optional[WindowLevel] = None) -> np.ndarray:
        """Get normalized pixel array for display (0-255 range)."""
        array = self.pixel_array.copy()
        
        # Handle photometric interpretation
        if self.photometric_interpretation == 'MONOCHROME1':
            # Invert grayscale for MONOCHROME1
            array = np.max(array) - array
        
        # Apply windowing if specified
        if window_level:
            window_min = window_level.center - window_level.width // 2
            window_max = window_level.center + window_level.width // 2
            array = np.clip(array, window_min, window_max)
            array = (array - window_min) / (window_max - window_min) * 255
        else:
            # Simple normalization
            array = ((array - np.min(array)) / 
                    (np.max(array) - np.min(array)) * 255)
        
        return array.astype(np.uint8)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get basic statistics about the pixel data."""
        return {
            'min': float(np.min(self.pixel_array)),
            'max': float(np.max(self.pixel_array)),
            'mean': float(np.mean(self.pixel_array)),
            'std': float(np.std(self.pixel_array)),
            'shape': list(self.pixel_array.shape)
        }

class ImageUploadRequest(FrozenModel):
    """Request for uploading a DICOM image."""
    user_id: str
    filename: str
    file_content: bytes
    patient_id: Optional[str] = None

    def validate_request(self) -> None:
        """Validate the upload request."""
        if not self.filename.lower().endswith(('.dcm', '.dicom')):
            raise ValueError("File must be a DICOM file (.dcm or .dicom)")
        
        if len(self.file_content) == 0:
            raise ValueError("File content cannot be empty")
        
        if len(self.file_content) > 100 * 1024 * 1024:  # 100MB limit
            raise ValueError("File size cannot exceed 100MB")


class ImageGenerationRequest(FrozenModel):
    """Request for image generation."""
    prompt: str
    negative_prompt: Optional[str] = None
    width: int = 512
    height: int = 512
    guidance_scale: float = 7.5
    num_inference_steps: int = 50
    seed: Optional[int] = None
    user_id: Optional[str] = None
    patient_id: Optional[str] = None
    session_id: Optional[str] = None

class GeneratedImage(FrozenModel):
    """Generated image data."""
    image_data: bytes
    image_format: str = "png"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    generation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=datetime.now)
    prompt: str = ""
    model_info: Dict[str, Any] = Field(default_factory=dict)

class ImageGenerationContext(FrozenModel):
    """Context for image generation."""
    user_query: str
    patient_context: Optional[PatientContext] = None
    chat_history: List[Dict[str, Any]] = Field(default_factory=list)
    medical_context: Optional[str] = None
    generation_purpose: GeneratedImagePurpose = GeneratedImagePurpose.EDUCATIONAL