"""OptiMed domain entities (v0).

All classes are **immutable** (Pydantic frozen models) and contain only
*side‑effect‑free* helper methods.  External I/O lives in adapters or
service layers.
"""

from datetime import datetime
from typing import Optional

from pydantic import Field

from .enums import Severity
from .mixins import FrozenModel

class KPIEvent(FrozenModel):
    metric: str
    value: float
    unit: str
    recorded_at: datetime = Field(default_factory=datetime.now(datetime.timezone.utc))
    metric_source: Optional[str] = None  # patient_id if applicable


class Alert(FrozenModel):
    alert_id: str
    message: str
    severity: Severity
    subject_id: Optional[str] = None  # patient_id if applicable
    created_at: datetime = Field(default_factory=datetime.now(datetime.timezone.utc))
    resolved_at: Optional[datetime] = None

    _ladder = {
        Severity.LOW: Severity.MEDIUM,
        Severity.MEDIUM: Severity.HIGH,
        Severity.HIGH: Severity.CRITICAL,
        Severity.CRITICAL: Severity.CRITICAL,  # no higher severity
    }

    def escalate(self) -> "Alert":
        return self.model_copy(update={"severity": self._ladder[self.severity]})