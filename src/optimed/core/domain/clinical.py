from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from pydantic import Field

from .enums import BedStatus, EncounterStatus, JournalEntryType
from .mixins import FrozenModel

"""Domain models for clinical data in the hospital system."""

class DataSource(FrozenModel):
    """Represents a source of data in the EHR."""
    source_type: str  # "observation", "condition", "medication", etc.
    resource_id: str  # FHIR resource ID
    resource_url: str  # Full URL to the resource in the EHR
    timestamp: datetime
    category: Optional[str] = None  # "vital-signs", "laboratory", etc.
    display_name: str = ""

class PatientContext(FrozenModel):

    patient_id: str
    name: str
    age: int
    sex: str
    care_unit: str
    vitals: Dict[str, str] = {}
    labs: Dict[str, str] = {}

    exam: Dict[str, str] = {}  # e.g. {"Abdomen": "Normal"}
    procedure: Dict[str, str] = {}  # Procedures from /Procedure
    social_history: Dict[str, str] = {}  # e.g. {"Smoking": "None", "Alcohol": "Occasional"}
    medications: Dict[str, str] = {}  # e.g. {"Aspirin": "81 mg daily"}
    allergies: Dict[str, str] = {}  # e.g. {"Penicillin": "Rash"}
    diagnoses: Dict[str, str] = {}  # e.g. {"Hypertension": "Controlled"}
    immunizations: Dict[str, str] = {}  # e.g. {"COVID-19 Vaccine": "2023-10-15"}

    # NEW: Observation-based data that used to be in imaging/procedure categories
    imaging_observations: Dict[str, str] = {}
    procedure_observations: Dict[str, str] = {}
    diagnostic_reports: Dict[str, str] = {}

    medication_statement: Dict[str, str] = {}
    questionnaire_response: Dict[str, str] = {}
    care_plan: Dict[str, str] = {}
    
    # Additional FHIR resources to make model more holistic
    family_history: Dict[str, str] = {}
    care_team: Dict[str, str] = {}
    goals: Dict[str, str] = {}
    clinical_impressions: Dict[str, str] = {}
    risk_assessments: Dict[str, str] = {}
    service_requests: Dict[str, str] = {}
    medication_administrations: Dict[str, str] = {}
    medication_dispenses: Dict[str, str] = {}
    immunization_recommendations: Dict[str, str] = {}
    appointments: Dict[str, str] = {}
    episodes_of_care: Dict[str, str] = {}
    imaging_studies: Dict[str, str] = {}
    devices: Dict[str, str] = {}
    device_use: Dict[str, str] = {}
    nutrition_orders: Dict[str, str] = {}
    adverse_events: Dict[str, str] = {}

    vitals_timestamps: Dict[str, str] = {}
    labs_timestamps: Dict[str, str] = {}
    exam_timestamps: Dict[str, str] = {}
    procedure_timestamps: Dict[str, str] = {}  # From /Procedure
    social_history_timestamps: Dict[str, str] = {}
    medications_timestamps: Dict[str, str] = {}
    allergies_timestamps: Dict[str, str] = {}
    diagnoses_timestamps: Dict[str, str] = {}
    immunizations_timestamps: Dict[str, str] = {}
    imaging_observations_timestamps: Dict[str, str] = {}
    procedure_observations_timestamps: Dict[str, str] = {}
    diagnostic_reports_timestamps: Dict[str, str] = {}
    medication_statement_timestamps: Dict[str, str] = {}
    questionnaire_response_timestamps: Dict[str, str] = {}
    care_plan_timestamps: Dict[str, str] = {}
    encounters: Dict[str, str] = {}
    encounters_timestamps: Dict[str, str] = {}
    
    # Timestamps for additional resources
    family_history_timestamps: Dict[str, str] = {}
    care_team_timestamps: Dict[str, str] = {}
    goals_timestamps: Dict[str, str] = {}
    clinical_impressions_timestamps: Dict[str, str] = {}
    risk_assessments_timestamps: Dict[str, str] = {}
    service_requests_timestamps: Dict[str, str] = {}
    medication_administrations_timestamps: Dict[str, str] = {}
    medication_dispenses_timestamps: Dict[str, str] = {}
    immunization_recommendations_timestamps: Dict[str, str] = {}
    appointments_timestamps: Dict[str, str] = {}
    episodes_of_care_timestamps: Dict[str, str] = {}
    imaging_studies_timestamps: Dict[str, str] = {}
    devices_timestamps: Dict[str, str] = {}
    device_use_timestamps: Dict[str, str] = {}
    nutrition_orders_timestamps: Dict[str, str] = {}
    adverse_events_timestamps: Dict[str, str] = {}

    # NEW: Data source tracking
    vitals_sources: Dict[str, DataSource] = {}
    labs_sources: Dict[str, DataSource] = {}
    exam_sources: Dict[str, DataSource] = {}
    procedure_sources: Dict[str, DataSource] = {}  # From /Procedure
    social_history_sources: Dict[str, DataSource] = {}
    medications_sources: Dict[str, DataSource] = {}
    allergies_sources: Dict[str, DataSource] = {}
    diagnoses_sources: Dict[str, DataSource] = {}
    immunizations_sources: Dict[str, DataSource] = {}
    imaging_observations_sources: Dict[str, DataSource] = {}
    procedure_observations_sources: Dict[str, DataSource] = {}
    diagnostic_reports_sources: Dict[str, DataSource] = {}
    medication_statement_sources: Dict[str, DataSource] = {}
    questionnaire_response_sources: Dict[str, DataSource] = {}
    care_plan_sources: Dict[str, DataSource] = {}
    encounters_sources: Dict[str, DataSource] = {}
    
    # Source tracking for additional resources
    family_history_sources: Dict[str, DataSource] = {}
    care_team_sources: Dict[str, DataSource] = {}
    goals_sources: Dict[str, DataSource] = {}
    clinical_impressions_sources: Dict[str, DataSource] = {}
    risk_assessments_sources: Dict[str, DataSource] = {}
    service_requests_sources: Dict[str, DataSource] = {}
    medication_administrations_sources: Dict[str, DataSource] = {}
    medication_dispenses_sources: Dict[str, DataSource] = {}
    immunization_recommendations_sources: Dict[str, DataSource] = {}
    appointments_sources: Dict[str, DataSource] = {}
    episodes_of_care_sources: Dict[str, DataSource] = {}
    imaging_studies_sources: Dict[str, DataSource] = {}
    devices_sources: Dict[str, DataSource] = {}
    device_use_sources: Dict[str, DataSource] = {}
    nutrition_orders_sources: Dict[str, DataSource] = {}
    adverse_events_sources: Dict[str, DataSource] = {}
    
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

