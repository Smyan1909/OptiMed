from .clinical import PatientContext, BedState, Encounter, JournalEntry, JournalEntryCreate, JournalEntryUpdate
from .diagnosis import DiagnosisResult, WebSearchInfo, CrossSessionHistoryInfo, GeneratedImageInfo, DifferentialDiagnosis
from .info import InfoEvent, Notification, CommThread, ChatMessage, WebSearchQuery, WebSearchResult, WebSearchResponse, ChatSession, SessionParticipant
from .kpi import KPIEvent, Alert
from .users import User, UserAction, UserSession, UserEHRConnection
from .image import DICOMMetadata, ImageDimensions, WindowLevel, DICOMImage, ImagePixelData, ImageUploadRequest, ImageGenerationContext, GeneratedImage, ImageGenerationRequest
from .enums import (
    BedStatus,
    EncounterStatus,
    EventType,
    Channel,
    NotificationStatus,
    Severity,
    ChatRole,
    UserRole,
    UserStatus,
    ImageModalityType,
    ImageStatus,
    JournalEntryType,
    GeneratedImagePurpose  # Only import the enum here
)

"""OptiMed domain entities (v0).

All classes are **immutable** (Pydantic frozen models) and contain only
*side‑effect‑free* helper methods.  External I/O lives in adapters or
service layers.
"""

__all__ = [
    # clinical
    "PatientContext",
    "BedState",
    "Encounter",
    "JournalEntry",
    "JournalEntryCreate", 
    "JournalEntryUpdate",
    # info
    "InfoEvent",
    "Notification",
    "CommThread",
    "ChatMessage",
    "ChatSession",
    "SessionParticipant",
    # kpi
    "KPIEvent",
    "Alert",
    # enums
    "BedStatus",
    "EncounterStatus",
    "EventType",
    "Channel",
    "NotificationStatus",
    "Severity",
    "ChatRole",
    "JournalEntryType",
    "GeneratedImagePurpose",
    # diagnosis
    "DiagnosisResult",
    "WebSearchInfo",
    "CrossSessionHistoryInfo",
    "GeneratedImageInfo",
    "DifferentialDiagnosis",
    # users
    "User",
    "UserAction",
    "UserSession",
    "UserRole",
    "UserStatus",
    "UserEHRConnection",
    # image
    "DICOMMetadata",
    "ImageDimensions",
    "ImagePixelData",
    "WindowLevel",
    "DICOMImage",
    "ImageUploadRequest",
    "ImageModalityType",
    "ImageStatus",
    "ImageGenerationContext",
    "GeneratedImage",
    "ImageGenerationRequest",
    # web search 
    "WebSearchQuery",
    "WebSearchResult",
    "WebSearchResponse",
]