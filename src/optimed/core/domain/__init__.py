from .clinical import PatientContext, BedState, Encounter
from .diagnosis import DiagnosisResult
from .info import InfoEvent, Notification, CommThread, ChatMessage
from .kpi import KPIEvent, Alert
from .enums import (
    BedStatus,
    EncounterStatus,
    EventType,
    Channel,
    NotificationStatus,
    Severity,
    ChatRole,
)

"""OptiMed domain entities (v0).

All classes are **immutable** (Pydantic frozen models) and contain only
*side‑effect‑free* helper methods.  External I/O lives in adapters or
service layers.
"""

__all__ = [
    # clinical
    "PatientContext",
    "Encounter",
    "BedState",
    # info
    "InfoEvent",
    "Notification",
    "CommThread",
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
    # diagnosis
    "DiagnosisResult",
]