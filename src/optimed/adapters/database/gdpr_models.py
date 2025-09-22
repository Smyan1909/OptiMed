"""
GDPR-safe SQLAlchemy ORM models for the new schema.

These models represent the new database schema that stores only metadata
and provenance information without any PHI content.
"""

from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean,
    ForeignKey, UniqueConstraint, Index, ARRAY,
    BigInteger, Float
)
from sqlalchemy.dialects.postgresql import UUID, BYTEA, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, Session
from sqlalchemy.sql import func

Base = declarative_base()

class SessionModel(Base):
    """Session tracking with pseudonymized patient IDs and audit trail."""
    
    __tablename__ = "sessions"
    
    session_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_hash = Column(BYTEA, nullable=False, comment="Salted hash of patient id")
    user_id = Column(UUID(as_uuid=True), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    lawful_basis = Column(String(100), nullable=False, comment="GDPR lawful basis for processing")
    purpose_of_use = Column(String(200), nullable=False, comment="Purpose limitation under GDPR")
    scopes = Column(ARRAY(String), nullable=True)
    model_config_hash = Column(BYTEA, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    
    # Relationships
    audit_events = relationship("AuditEventModel", back_populates="session", cascade="all, delete-orphan")
    evidence_sets = relationship("EvidenceSetModel", back_populates="session", cascade="all, delete-orphan")
    
    # Indexes
    __table_args__ = (
        Index("ix_sessions_subject_hash", "subject_hash"),
        Index("ix_sessions_user_id", "user_id"),
        Index("ix_sessions_tenant_id", "tenant_id"),
        Index("ix_sessions_started_at", "started_at"),
    )

class AuditEventModel(Base):
    """Audit trail for all data access and processing activities."""
    
    __tablename__ = "audit_events"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    action = Column(String(50), nullable=False, comment="Type of action performed")
    resource_type = Column(String(100), nullable=True)
    resource_id = Column(String(255), nullable=True)
    resource_version = Column(String(50), nullable=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    outcome = Column(String(50), nullable=True)
    latency_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    
    # Relationships
    session = relationship("SessionModel", back_populates="audit_events")
    
    # Indexes
    __table_args__ = (
        Index("ix_audit_events_session_id", "session_id"),
        Index("ix_audit_events_action", "action"),
        Index("ix_audit_events_occurred_at", "occurred_at"),
    )

class ResourceModel(Base):
    """FHIR resource metadata catalog without PHI content."""
    
    __tablename__ = "resources"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    subject_hash = Column(BYTEA, nullable=False, comment="Pseudonymized patient identifier")
    server_alias = Column(String(100), nullable=False)
    resource_type = Column(String(100), nullable=False)
    resource_id = Column(String(255), nullable=False)
    version_id = Column(String(50), nullable=True)
    last_updated = Column(DateTime(timezone=True), nullable=True)
    etag = Column(String(100), nullable=True)
    encounter_id = Column(String(255), nullable=True)
    period_start = Column(DateTime(timezone=True), nullable=True)
    period_end = Column(DateTime(timezone=True), nullable=True)
    has_binary = Column(Boolean, default=False)
    byte_size = Column(Integer, nullable=True)
    sha256 = Column(BYTEA, nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    
    # Relationships
    codes = relationship("ResourceCodeModel", back_populates="resource", cascade="all, delete-orphan")
    
    # Constraints and Indexes
    __table_args__ = (
        UniqueConstraint("subject_hash", "server_alias", "resource_type", "resource_id", "version_id", 
                        name="uq_resources_unique"),
        Index("ix_resources_subject_type_date", "subject_hash", "resource_type", "last_updated"),
        Index("ix_resources_server_alias", "server_alias"),
        Index("ix_resources_resource_type", "resource_type"),
    )

class ResourceCodeModel(Base):
    """Medical codes and terminologies from FHIR resources."""
    
    __tablename__ = "resource_codes"
    
    resource_fk = Column(BigInteger, ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True)
    system = Column(String(255), primary_key=True)
    code = Column(String(100), primary_key=True)
    display = Column(Text, nullable=True)
    units = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    
    # Relationships
    resource = relationship("ResourceModel", back_populates="codes")
    
    # Indexes
    __table_args__ = (
        Index("ix_resource_codes_code", "system", "code"),
        Index("ix_resource_codes_display", "display"),
    )

class EvidenceSetModel(Base):
    """Evidence pointers for retrieval without storing content."""
    
    __tablename__ = "evidence_sets"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    question_id = Column(UUID(as_uuid=True), nullable=False)
    rank = Column(Integer, nullable=False)
    resource_type = Column(String(100), nullable=False)
    resource_id = Column(String(255), nullable=False)
    resource_version = Column(String(50), nullable=True)
    section = Column(String(100), nullable=True)
    start_offset = Column(Integer, nullable=True)
    end_offset = Column(Integer, nullable=True)
    rerank_score = Column(Float, nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    
    # Relationships
    session = relationship("SessionModel", back_populates="evidence_sets")
    
    # Indexes
    __table_args__ = (
        Index("ix_evidence_sets_session_id", "session_id"),
        Index("ix_evidence_sets_question_id", "question_id"),
        Index("ix_evidence_sets_rank", "rank"),
    )

class ModelRegistryModel(Base):
    """Model configurations for reproducibility."""
    
    __tablename__ = "model_registry"
    
    name = Column(String(100), primary_key=True)
    version = Column(String(50), primary_key=True)
    config_json = Column(JSONB, nullable=True)
    config_hash = Column(BYTEA, nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

class RetrievalConfigModel(Base):
    """Retrieval algorithm configurations."""
    
    __tablename__ = "retrieval_config"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime(timezone=True), default=func.now())
    params = Column(JSONB, nullable=True)
    config_hash = Column(BYTEA, nullable=True)
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    
    # Indexes
    __table_args__ = (
        Index("ix_retrieval_config_config_hash", "config_hash"),
    )

class TempContentModel(Base):
    """Ephemeral encrypted cache with crypto-shredding."""
    
    __tablename__ = "temp_content"
    
    session_id = Column(UUID(as_uuid=True), primary_key=True)
    resource_type = Column(String(100), primary_key=True)
    resource_id = Column(String(255), primary_key=True)
    dek_id = Column(String(255), nullable=False, comment="Data Encryption Key ID")
    ciphertext = Column(BYTEA, nullable=False, comment="AES-GCM encrypted content")
    created_at = Column(DateTime(timezone=True), default=func.now())
    ttl_at = Column(DateTime(timezone=True), nullable=False, comment="Time to live for crypto-shredding")
    
    # Indexes
    __table_args__ = (
        Index("ix_temp_content_ttl", "ttl_at"),
    )

# GDPR-safe user models
class UserGDPRSafeModel(Base):
    """GDPR-compliant users table with pseudonymized PII."""
    
    __tablename__ = "users_gdpr_safe"
    
    user_id = Column(String(255), primary_key=True)
    username = Column(String(255), unique=True, nullable=False)
    email_hash = Column(String(255), nullable=False, comment="Pseudonymized email")
    name_hash = Column(String(255), nullable=False, comment="Pseudonymized name")
    role = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False, default="active")
    department = Column(String(255), nullable=True)
    license_number = Column(String(255), nullable=True)
    phone_hash = Column(String(255), nullable=True, comment="Pseudonymized phone")
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    
    # Indexes
    __table_args__ = (
        Index("ix_users_gdpr_safe_username", "username"),
        Index("ix_users_gdpr_safe_email_hash", "email_hash"),
        Index("ix_users_gdpr_safe_role", "role"),
    )

class UserSessionGDPRSafeModel(Base):
    """GDPR-compliant user sessions table."""
    
    __tablename__ = "user_sessions_gdpr_safe"
    
    session_id = Column(String(255), primary_key=True)
    user_id = Column(String(255), ForeignKey("users_gdpr_safe.user_id", ondelete="CASCADE"), nullable=False)
    login_time = Column(DateTime(timezone=True), nullable=False)
    last_activity = Column(DateTime(timezone=True), nullable=False)
    ip_address_hash = Column(String(255), nullable=True, comment="Pseudonymized IP")
    user_agent_hash = Column(String(255), nullable=True, comment="Pseudonymized user agent")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    
    # Relationships
    user = relationship("UserGDPRSafeModel")
    
    # Indexes
    __table_args__ = (
        Index("ix_user_sessions_gdpr_safe_user_id", "user_id"),
        Index("ix_user_sessions_gdpr_safe_active", "is_active"),
    )

class UserActionGDPRSafeModel(Base):
    """GDPR-compliant user actions table with pseudonymized resource IDs."""
    
    __tablename__ = "user_actions_gdpr_safe"
    
    action_id = Column(String(255), primary_key=True)
    user_id = Column(String(255), ForeignKey("users_gdpr_safe.user_id", ondelete="CASCADE"), nullable=False)
    action_type = Column(String(100), nullable=False)
    resource_type = Column(String(100), nullable=True)
    resource_id_hash = Column(String(255), nullable=True, comment="Pseudonymized resource ID")
    description = Column(Text, nullable=False)
    metadata = Column(JSONB, default={})
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    
    # Relationships
    user = relationship("UserGDPRSafeModel")
    
    # Indexes
    __table_args__ = (
        Index("ix_user_actions_gdpr_safe_user_id", "user_id"),
        Index("ix_user_actions_gdpr_safe_type", "action_type"),
        Index("ix_user_actions_gdpr_safe_created_at", "created_at"),
    )

# Utility functions for working with the models
class GDPRModelUtils:
    """Utility functions for working with GDPR-safe models."""
    
    @staticmethod
    def create_session(
        session: Session,
        subject_hash: bytes,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        lawful_basis: str,
        purpose_of_use: str,
        scopes: Optional[List[str]] = None,
        model_config_hash: bytes = b""
    ) -> SessionModel:
        """Create a new session with proper GDPR fields."""
        session_model = SessionModel(
            subject_hash=subject_hash,
            user_id=user_id,
            tenant_id=tenant_id,
            lawful_basis=lawful_basis,
            purpose_of_use=purpose_of_use,
            scopes=scopes or [],
            model_config_hash=model_config_hash
        )
        session.add(session_model)
        return session_model
    
    @staticmethod
    def log_audit_event(
        session: Session,
        session_id: uuid.UUID,
        action: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        resource_version: Optional[str] = None,
        outcome: Optional[str] = None,
        latency_ms: Optional[int] = None
    ) -> AuditEventModel:
        """Log an audit event."""
        audit_event = AuditEventModel(
            session_id=session_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_version=resource_version,
            outcome=outcome,
            latency_ms=latency_ms
        )
        session.add(audit_event)
        return audit_event
    
    @staticmethod
    def create_resource(
        session: Session,
        subject_hash: bytes,
        server_alias: str,
        resource_type: str,
        resource_id: str,
        version_id: Optional[str] = None,
        last_updated: Optional[datetime] = None,
        etag: Optional[str] = None,
        encounter_id: Optional[str] = None,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
        has_binary: bool = False,
        byte_size: Optional[int] = None,
        sha256: Optional[bytes] = None
    ) -> ResourceModel:
        """Create a new resource record."""
        resource = ResourceModel(
            subject_hash=subject_hash,
            server_alias=server_alias,
            resource_type=resource_type,
            resource_id=resource_id,
            version_id=version_id,
            last_updated=last_updated,
            etag=etag,
            encounter_id=encounter_id,
            period_start=period_start,
            period_end=period_end,
            has_binary=has_binary,
            byte_size=byte_size,
            sha256=sha256
        )
        session.add(resource)
        return resource
    
    @staticmethod
    def create_evidence_set(
        session: Session,
        session_id: uuid.UUID,
        question_id: uuid.UUID,
        rank: int,
        resource_type: str,
        resource_id: str,
        resource_version: Optional[str] = None,
        section: Optional[str] = None,
        start_offset: Optional[int] = None,
        end_offset: Optional[int] = None,
        rerank_score: Optional[float] = None,
        reason: Optional[str] = None
    ) -> EvidenceSetModel:
        """Create a new evidence set record."""
        evidence_set = EvidenceSetModel(
            session_id=session_id,
            question_id=question_id,
            rank=rank,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_version=resource_version,
            section=section,
            start_offset=start_offset,
            end_offset=end_offset,
            rerank_score=rerank_score,
            reason=reason
        )
        session.add(evidence_set)
        return evidence_set
