"""
GDPR Data Subject Rights Request (DSAR) Endpoints

Handles GDPR Article 15-22 requests:
- Article 15: Right of Access
- Article 16: Right to Rectification
- Article 17: Right to Erasure
- Article 18: Right to Restriction
- Article 20: Right to Data Portability
- Article 21: Right to Object
"""

import uuid
import hashlib
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta

from optimed.core.domain import User
from optimed.adapters.security.auth_middleware import require_authenticated_user
from optimed.core.logging_utils import get_logger, log_error

logger = get_logger(__name__)

gdpr_router = APIRouter(prefix="/gdpr", tags=["GDPR Compliance"])


class DSARRequest(BaseModel):
    request_type: str  # "access", "erasure", "portability", "rectification", "restriction", "object"
    patient_id: Optional[str] = None
    data_categories: List[str]
    reason: Optional[str] = None


class DSARResponse(BaseModel):
    request_id: str
    status: str
    estimated_completion: datetime
    message: str


class AuditTrailResponse(BaseModel):
    user_id: str
    audit_trail: List[dict]
    total_records: int
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None


@gdpr_router.post("/dsar/request", response_model=DSARResponse)
async def create_dsar_request(
    request: Request,
    dsar: DSARRequest,
    user: User = Depends(require_authenticated_user)
):
    """
    Submit a Data Subject Access Request (DSAR) per GDPR Articles 15-22.

    Request types:
    - access: Right of Access (Article 15)
    - rectification: Right to Rectification (Article 16)
    - erasure: Right to Erasure / Right to be Forgotten (Article 17)
    - restriction: Right to Restriction of Processing (Article 18)
    - portability: Right to Data Portability (Article 20)
    - object: Right to Object (Article 21)
    """

    # Validate request type
    valid_types = ["access", "rectification", "erasure", "restriction", "portability", "object"]
    if dsar.request_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid request type. Must be one of: {', '.join(valid_types)}"
        )

    # Get audit repository from app state
    if not hasattr(request.app.state, '_audit_repo'):
        raise HTTPException(status_code=500, detail="Audit repository not available")

    audit_repo = request.app.state._audit_repo

    request_id = str(uuid.uuid4())

    # Log compliance event (GDPR Article 30 - Records of Processing Activities)
    try:
        await audit_repo.log_compliance_event(
            event_type=f"dsar_{dsar.request_type}_request",
            compliance_framework="GDPR",
            session_id=getattr(request.state, 'session_id', None),
            user_id=user.user_id,
            patient_id_hash=hashlib.sha256(dsar.patient_id.encode()).hexdigest() if dsar.patient_id else None,
            data_categories=dsar.data_categories,
            processing_purposes=["data_subject_rights"],
            lawful_basis=f"GDPR Article {_get_article_number(dsar.request_type)}",
            compliance_status="pending"
        )
    except Exception as e:
        log_error(logger, "DSAR request logging", e)

    # GDPR requires response within 30 days (1 month)
    completion_date = datetime.now() + timedelta(days=30)

    return DSARResponse(
        request_id=request_id,
        status="pending",
        estimated_completion=completion_date,
        message=f"Your {dsar.request_type} request has been received (ID: {request_id}). "
                f"We will respond within 30 days as required by GDPR Article {_get_article_number(dsar.request_type).split(' -')[0]}."
    )


def _get_article_number(request_type: str) -> str:
    """Map DSAR request type to GDPR article number."""
    mapping = {
        "access": "15 - Right of Access",
        "rectification": "16 - Right to Rectification",
        "erasure": "17 - Right to Erasure (Right to be Forgotten)",
        "restriction": "18 - Right to Restriction of Processing",
        "portability": "20 - Right to Data Portability",
        "object": "21 - Right to Object"
    }
    return mapping.get(request_type, "Unknown")


@gdpr_router.get("/audit-trail", response_model=AuditTrailResponse)
async def get_user_audit_trail(
    request: Request,
    user: User = Depends(require_authenticated_user),
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = 1000
):
    """
    Get user's own audit trail (GDPR Article 15 - Right of Access).

    Returns GDPR-compliant audit logs showing:
    - What data was accessed
    - When it was accessed
    - For what purpose
    - Under what lawful basis
    """

    # Get audit repository from app state
    if not hasattr(request.app.state, '_audit_repo'):
        raise HTTPException(status_code=500, detail="Audit repository not available")

    audit_repo = request.app.state._audit_repo

    # Fetch audit trail
    try:
        audit_trail = await audit_repo.get_user_audit_trail(
            user_id=user.user_id,
            from_date=from_date,
            to_date=to_date,
            limit=limit
        )
    except Exception as e:
        log_error(logger, "Audit trail fetch", e)
        raise HTTPException(status_code=500, detail="Error fetching audit trail")

    # Log compliance event for accessing audit trail
    try:
        await audit_repo.log_compliance_event(
            event_type="dsar_audit_trail_accessed",
            compliance_framework="GDPR",
            session_id=getattr(request.state, 'session_id', None),
            user_id=user.user_id,
            data_categories=["audit_logs"],
            processing_purposes=["data_subject_rights", "transparency"],
            lawful_basis="GDPR Article 15 - Right of Access",
            compliance_status="compliant"
        )
    except Exception as e:
        log_error(logger, "Audit trail access logging", e)

    return AuditTrailResponse(
        user_id=user.user_id,
        audit_trail=audit_trail,
        total_records=len(audit_trail),
        from_date=from_date,
        to_date=to_date
    )


@gdpr_router.get("/data-categories")
async def get_data_categories(
    user: User = Depends(require_authenticated_user)
):
    """
    Get list of data categories processed by the system.

    Helps users understand what types of data are being processed (GDPR Article 13/14 - Transparency).
    """
    return {
        "data_categories": [
            {
                "category": "health_data",
                "description": "Medical records, diagnoses, treatments, lab results",
                "sensitivity": "high",
                "retention_period_days": 3650  # 10 years (typical medical records retention)
            },
            {
                "category": "personal_identifiers",
                "description": "Name, patient ID, date of birth",
                "sensitivity": "high",
                "retention_period_days": 3650
            },
            {
                "category": "health_documents",
                "description": "Uploaded PDF documents, images, reports",
                "sensitivity": "high",
                "retention_period_days": 3650
            },
            {
                "category": "clinical_reports",
                "description": "Diagnostic reports, imaging studies, pathology reports",
                "sensitivity": "high",
                "retention_period_days": 3650
            },
            {
                "category": "medical_imaging",
                "description": "DICOM images, X-rays, CT scans, MRI scans",
                "sensitivity": "high",
                "retention_period_days": 3650
            },
            {
                "category": "diagnostic_data",
                "description": "AI-generated diagnoses and clinical decision support outputs",
                "sensitivity": "high",
                "retention_period_days": 3650
            },
            {
                "category": "audit_logs",
                "description": "Access logs, system usage logs (no PHI content)",
                "sensitivity": "low",
                "retention_period_days": 2555  # 7 years (GDPR recommendation)
            }
        ],
        "lawful_bases": [
            "Article 6(1)(c) - Legal obligation (healthcare delivery)",
            "Article 9(2)(h) - Healthcare and medical diagnosis"
        ],
        "data_retention_policy": "Medical data: 10 years, Audit logs: 7 years",
        "encryption_methods": ["AES-256-GCM (data at rest)", "TLS 1.3 (data in transit)"]
    }


@gdpr_router.post("/consent/withdraw")
async def withdraw_consent(
    request: Request,
    user: User = Depends(require_authenticated_user),
    consent_type: str = "all"
):
    """
    Withdraw consent for data processing (GDPR Article 7(3) - Right to Withdraw Consent).

    Note: In healthcare contexts, consent withdrawal may be limited by legal obligations.
    """

    # Get audit repository
    if not hasattr(request.app.state, '_audit_repo'):
        raise HTTPException(status_code=500, detail="Audit repository not available")

    audit_repo = request.app.state._audit_repo

    # Log consent withdrawal (GDPR compliance)
    try:
        await audit_repo.log_compliance_event(
            event_type="consent_withdrawn",
            compliance_framework="GDPR",
            session_id=getattr(request.state, 'session_id', None),
            user_id=user.user_id,
            data_categories=["health_data", "personal_identifiers"],
            processing_purposes=["healthcare_delivery", "clinical_decision_support"],
            lawful_basis="GDPR Article 7(3) - Right to Withdraw Consent",
            compliance_status="compliant"
        )
    except Exception as e:
        log_error(logger, "Consent withdrawal logging", e)

    return {
        "status": "consent_withdrawn",
        "message": "Your consent has been withdrawn. Please note that we may still need to retain certain "
                   "data to comply with legal obligations (e.g., medical records retention requirements).",
        "consent_type": consent_type,
        "withdrawal_date": datetime.now().isoformat()
    }
