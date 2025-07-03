from enum import Enum

"""Enum definitions shared across the domain layer."""

__all__ = [
    "BedStatus",
    "EncounterStatus",
    "EventType",
    "Channel",
    "NotificationStatus",
    "Severity",
]


class BedStatus(str, Enum):
    VACANT = "VACANT"
    OCCUPIED = "OCCUPIED"
    CLEANING = "CLEANING"

class EncounterStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    DISCHARGED = "DISCHARGED"

class EventType(str, Enum):
    ADMISSION = "ADMISSION"
    DISCHARGE = "DISCHARGE"
    TRANSFER = "TRANSFER"
    # Vitals
    VITAL_READING = "VITAL_READING"
    VITAL_ALERT = "VITAL_ALERT"

    # Labs
    LAB_RESULT = "LAB_RESULT"
    LAB_CRIT = "LAB_CRIT"

    # Imaging
    RAD_READY = "RAD_READY"
    RAD_CRIT = "RAD_CRIT"

    # Medication & orders
    MED_ORDER = "MED_ORDER"
    MED_INTERACTION = "MED_INTERACTION"

    # Patient movement / logistics
    PATIENT_MOVE = "PATIENT_MOVE"
    BED_STATE_CHANGE = "BED_STATE_CHANGE"

    # System capacity
    SYS_BACKLOG = "SYS_BACKLOG"
    SYS_CRIT_BACKLOG = "SYS_CRIT_BACKLOG"

    # Documentation / NLP watch
    NOTE_NEW = "NOTE_NEW"
    NOTE_SEPSIS_KEYWORD = "NOTE_SEPSIS_KEYWORD"

class Channel(str, Enum):
    TEAMS = "TEAMS"
    EMAIL = "EMAIL"
    ASCOM = "ASCOM"
    SMS = "SMS"
    IN_APP = "IN_APP"

class NotificationStatus(str, Enum):
    DELIVERED = "DELIVERED"
    ACK = "ACK"
    TIMEOUT = "TIMEOUT"

class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

class ChatRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class UserRole(str, Enum):
    ADMIN = "admin"
    DOCTOR = "doctor"
    NURSE = "nurse"
    TECHNICIAN = "technician"
    OTHER_STAFF = "other_staff"

class UserStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    PENDING = "pending"

class ImageModalityType(str, Enum):
    "DICOM image modality types."
    CT = "CT"
    MRI = "MRI"
    XRAY = "CR"
    ULTRASOUND = "US"
    MAMMOGRAPHY = "MG"
    NUCLEAR = "NM"
    PET = "PT"
    OTHER = "OT"

class ImageStatus(str, Enum):
    "Status of the image in the system."
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    ERROR = "ERROR"