import io
import pydicom 
import numpy as np 

from optimed.core.domain import (
    DICOMMetadata,
    ImageDimensions,
    ImagePixelData,
    WindowLevel,
    ImageModalityType,
)

from optimed.core.ports import DICOMProcessor


class PyDICOMProcessor(DICOMProcessor):
    """DICOM processing adapter using pydicom library."""
    
    async def validate_dicom_file(self, file_content: bytes) -> bool:
        """Validate if file is a valid DICOM file."""
        try:
            pydicom.dcmread(io.BytesIO(file_content))
            return True
        except Exception:
            return False
    
    async def extract_metadata(self, file_content: bytes) -> DICOMMetadata:
        """Extract metadata from DICOM file."""
        dicom_data = pydicom.dcmread(io.BytesIO(file_content))
        
        # Map DICOM modality to our enum
        modality = None
        if hasattr(dicom_data, 'Modality'):
            modality_str = str(dicom_data.Modality)
            try:
                modality = ImageModalityType(modality_str)
            except ValueError:
                modality = ImageModalityType.OTHER
        
        # Extract pixel spacing as list
        pixel_spacing = None
        if hasattr(dicom_data, 'PixelSpacing'):
            pixel_spacing = [float(x) for x in dicom_data.PixelSpacing]
        
        # Extract image position
        image_position = None
        if hasattr(dicom_data, 'ImagePositionPatient'):
            image_position = [float(x) for x in dicom_data.ImagePositionPatient]
        
        # Extract image orientation
        image_orientation = None
        if hasattr(dicom_data, 'ImageOrientationPatient'):
            image_orientation = [float(x) for x in dicom_data.ImageOrientationPatient]
        
        return DICOMMetadata(
            patient_name=str(dicom_data.PatientName) if hasattr(dicom_data, 'PatientName') else None,
            patient_id=str(dicom_data.PatientID) if hasattr(dicom_data, 'PatientID') else None,
            study_date=str(dicom_data.StudyDate) if hasattr(dicom_data, 'StudyDate') else None,
            study_time=str(dicom_data.StudyTime) if hasattr(dicom_data, 'StudyTime') else None,
            modality=modality,
            series_description=str(dicom_data.SeriesDescription) if hasattr(dicom_data, 'SeriesDescription') else None,
            study_description=str(dicom_data.StudyDescription) if hasattr(dicom_data, 'StudyDescription') else None,
            body_part_examined=str(dicom_data.BodyPartExamined) if hasattr(dicom_data, 'BodyPartExamined') else None,
            slice_thickness=float(dicom_data.SliceThickness) if hasattr(dicom_data, 'SliceThickness') else None,
            pixel_spacing=pixel_spacing,
            image_position=image_position,
            image_orientation=image_orientation,
            window_center=float(dicom_data.WindowCenter) if hasattr(dicom_data, 'WindowCenter') else None,
            window_width=float(dicom_data.WindowWidth) if hasattr(dicom_data, 'WindowWidth') else None,
            rows=int(dicom_data.Rows) if hasattr(dicom_data, 'Rows') else None,
            columns=int(dicom_data.Columns) if hasattr(dicom_data, 'Columns') else None,
            bits_allocated=int(dicom_data.BitsAllocated) if hasattr(dicom_data, 'BitsAllocated') else None,
            bits_stored=int(dicom_data.BitsStored) if hasattr(dicom_data, 'BitsStored') else None,
        )
    
    async def extract_pixel_data(self, file_content: bytes, image_id: str) -> ImagePixelData:
        """Extract pixel data from DICOM file."""
        dicom_data = pydicom.dcmread(io.BytesIO(file_content))
        
        # Get pixel array
        pixel_array = dicom_data.pixel_array
        
        return ImagePixelData(
            image_id=image_id,  # Use the provided image_id
            pixel_array=pixel_array,
            original_dtype=str(pixel_array.dtype),
            photometric_interpretation=getattr(dicom_data, 'PhotometricInterpretation', None)
        )
    
    async def get_image_dimensions(self, file_content: bytes) -> ImageDimensions:
        """Get image dimensional information."""
        dicom_data = pydicom.dcmread(io.BytesIO(file_content))
        
        # Basic dimensions
        width = int(dicom_data.Columns) if hasattr(dicom_data, 'Columns') else 0
        height = int(dicom_data.Rows) if hasattr(dicom_data, 'Rows') else 0
        
        # Pixel spacing
        pixel_spacing_x = None
        pixel_spacing_y = None
        if hasattr(dicom_data, 'PixelSpacing'):
            pixel_spacing_x = float(dicom_data.PixelSpacing[0])
            pixel_spacing_y = float(dicom_data.PixelSpacing[1])
        
        # Slice thickness
        slice_thickness = None
        if hasattr(dicom_data, 'SliceThickness'):
            slice_thickness = float(dicom_data.SliceThickness)
        
        # Check if this is a 3D volume (for future multi-slice support)
        depth = None
        if hasattr(dicom_data, 'NumberOfFrames'):
            depth = int(dicom_data.NumberOfFrames)
        
        return ImageDimensions(
            width=width,
            height=height,
            depth=depth,
            pixel_spacing_x=pixel_spacing_x,
            pixel_spacing_y=pixel_spacing_y,
            slice_thickness=slice_thickness
        )
    
    async def get_default_window_level(self, file_content: bytes) -> WindowLevel:
        """Get default window/level settings from DICOM file."""
        dicom_data = pydicom.dcmread(io.BytesIO(file_content))
        
        # Try to get window center and width from DICOM
        if hasattr(dicom_data, 'WindowCenter') and hasattr(dicom_data, 'WindowWidth'):
            # Handle multiple window values (take the first one)
            center = dicom_data.WindowCenter
            width = dicom_data.WindowWidth
            
            if hasattr(center, '__iter__') and not isinstance(center, str):
                center = center[0]
            if hasattr(width, '__iter__') and not isinstance(width, str):
                width = width[0]
                
            return WindowLevel(center=float(center), width=float(width))
        
        # Calculate default window/level from pixel data
        pixel_array = dicom_data.pixel_array
        min_val = float(np.min(pixel_array))
        max_val = float(np.max(pixel_array))
        
        center = (max_val + min_val) / 2
        width = max_val - min_val
        
        return WindowLevel(center=center, width=width)