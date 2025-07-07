from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from pydantic import Field

from .enums import BedStatus, EncounterStatus, JournalEntryType
from .mixins import FrozenModel

"""Domain models for clinical data in the hospital system."""

class PatientContext(FrozenModel):

    patient_id: str
    name: str
    age: int
    sex: str
    care_unit: str
    vitals: Dict[str, str] = {}
    labs: Dict[str, str] = {}

    imaging: Dict[str, str] = {}  # e.g. {"CT Chest": "2023-10-01"}
    exam: Dict[str, str] = {}  # e.g. {"Abdomen": "Normal"}
    procedure: Dict[str, str] = {}  # e.g. {"Appendectomy": "2023-10-02"}
    social_history: Dict[str, str] = {}  # e.g. {"Smoking": "None", "Alcohol": "Occasional"}
    medications: Dict[str, str] = {}  # e.g. {"Aspirin": "81 mg daily"}
    allergies: Dict[str, str] = {}  # e.g. {"Penicillin": "Rash"}
    diagnoses: Dict[str, str] = {}  # e.g. {"Hypertension": "Controlled"}

    
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def has_critical_lab(self) -> bool:
        """Returns True if any lab value breaches critical threshold.

        In MVP we hard‑code potassium > 6.0 mmol/L as example.
        Later versions will pull thresholds from hospital config.
        """
        k = self.labs.get("K⁺") or self.labs.get("K+", None)
        return k is not None and float(k) >= 6.0
    
    def critical_lab_msgs(self) -> List[str]:
        """Returns list of critical lab messages."""
        msgs: List[str] = []
        if self.has_critical_lab():
            k = self.labs.get("K⁺") or self.labs.get("K+", None)
            if k is not None and float(k) >= 6.0:
                msgs.append(f"Critical hyperkalemia: K+ = {k} mmol/L (normal: 3.5-5.0)")
        return msgs
    

class BedState(FrozenModel):
    bed_id: str
    care_unit: str
    status: BedStatus
    since: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    current_encounter: Optional[str] = None # FK to EncounterID

    def idle_minutes(self, now: Optional[datetime] = None) -> int:
        """Minutes bed has been VACANT or CLEANING."""
        if self.status == BedStatus.OCCUPIED:
            return 0
        now = now or datetime.now(timezone.utc)
        return int((now - self.since).total_seconds() // 60)
    
class Encounter(FrozenModel):
    encounter_id: str
    patient_id: str
    status: EncounterStatus
    admit_ts: datetime
    discharge_ts: Optional[datetime] = None
    bed_history: List[BedState] = Field(default_factory=list)

    def length_of_stay(self, now: Optional[datetime] = None) -> timedelta:
        """Calculate length of stay."""
        end_time = self.discharge_ts or now or datetime.now(timezone.utc)
        return end_time - self.admit_ts

class JournalEntry(FrozenModel):
    """Medical journal entry for patient care documentation."""
    
    entry_id: str
    patient_id: str
    title: str
    content: str
    entry_type: JournalEntryType
    created_by: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    author_name: str
    author_role: str
    
    def is_recent(self, hours: int = 24) -> bool:
        """Check if entry was created within the last N hours."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return self.created_at >= cutoff
    
    def word_count(self) -> int:
        """Count words in the content."""
        return len(self.content.split())

class JournalEntryCreate(FrozenModel):
    """Request model for creating a new journal entry."""
    
    patient_id: str
    title: str
    content: str
    entry_type: JournalEntryType

class JournalEntryUpdate(FrozenModel):
    """Request model for updating an existing journal entry."""
    
    title: Optional[str] = None
    content: Optional[str] = None
    entry_type: Optional[JournalEntryType] = None

