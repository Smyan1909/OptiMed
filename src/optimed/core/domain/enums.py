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