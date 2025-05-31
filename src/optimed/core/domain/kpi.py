from datetime import datetime, timezone
from typing import Optional

from pydantic import Field

from .enums import Severity
from .mixins import FrozenModel

"""Domain models for Key Performance Indicators (KPIs) and Alerts in the hospital system."""

class KPIEvent(FrozenModel):
    metric: str
    value: float
    unit: str
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metric_source: Optional[str] = None  # patient_id if applicable


class Alert(FrozenModel):
    alert_id: str
    message: str
    severity: Severity
    subject_id: Optional[str] = None  # patient_id if applicable
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None

    _ladder = {
        Severity.LOW: Severity.MEDIUM,
        Severity.MEDIUM: Severity.HIGH,
        Severity.HIGH: Severity.CRITICAL,
        Severity.CRITICAL: Severity.CRITICAL,  # no higher severity
    }

    def escalate(self) -> "Alert":
        return self.model_copy(update={"severity": self._ladder[self.severity]})