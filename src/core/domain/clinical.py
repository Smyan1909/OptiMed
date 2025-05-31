from __future__ import annotations

"""OptiMed domain entities (v0).

All classes are **immutable** (Pydantic frozen models) and contain only
*side‑effect‑free* helper methods.  External I/O lives in adapters or
service layers.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from pydantic import Field

from .enums import BedStatus, EncounterStatus
from .mixins import FrozenModel

class PatientContext(FrozenModel):

    patient_id: str
    name: str
    age: int
    sex: str
    care_unit: str
    vitals: Dict[str, str] = {}
    labs: Dict[str, str] = {}
    updated_at: datetime = Field(default_factory=datetime.now(datetime.timezone.utc))

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
            msgs.append(f"Potassium critical: {self.labs.get('K⁺') or self.labs.get('K+')}")
        return msgs
    

class BedState(FrozenModel):
    bed_id: str
    care_unit: str
    status: BedStatus
    since: datetime = Field(default_factory=datetime.now(datetime.timezone.utc))
    current_encounter: Optional[str] = None # FK to EncounterID

    def idle_minutes(self, now: Optional[datetime] = None) -> int:
        """Minutes bed has been VACANT or CLEANING."""
        if self.status == BedStatus.OCCUPIED:
            return 0
        now = now or datetime.now(datetime.timezone.utc)
        return int((now - self.since).total_seconds() // 60)
    
class Encounter(FrozenModel):
    encounter_id: str
    patient_id: str
    status: EncounterStatus
    admit_ts: datetime
    discharge_ts: Optional[datetime] = None
    bed_history: List[BedState] = Field(default_factory=list)


    def length_of_stay(self, now: Optional[datetime] = None) -> timedelta:
        end = self.discharge_ts or now or datetime.now(datetime.timezone.utc)
        return end - self.admit_ts


