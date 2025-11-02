"""
Audit Repository for OptiMed

Implements comprehensive audit logging with GDPR compliance.
Logs API requests, data access, data lineage, and usage metrics without storing PHI.
"""

import asyncpg
import uuid
import json
import hashlib
from typing import Optional, Dict, Any, List
from datetime import datetime
from optimed.adapters.security.encryption_service import get_phi_redactor
from optimed.adapters.security.database_encryption import DatabaseEncryption
from optimed.core.logging_utils import get_logger, log_error

logger = get_logger(__name__)


class PGAuditRepository:
    """PostgreSQL-based audit repository with GDPR-safe logging."""

    def __init__(self, dsn: str, min_size: int = 5, max_size: int = 20):
        self.dsn = dsn
        self.min_size = min_size
        self.max_size = max_size
        self._pool: Optional[asyncpg.Pool] = None
        self.phi_redactor = get_phi_redactor()

    async def _get_pool(self) -> asyncpg.Pool:
        """Get or create the connection pool."""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                dsn=self.dsn,
                min_size=self.min_size,
                max_size=self.max_size
            )
        return self._pool

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    def _hash_sensitive_data(self, data: str) -> str:
        """Create SHA256 hash of sensitive data for logging."""
        return hashlib.sha256(data.encode()).hexdigest()

    def _to_uuid(self, value: Optional[str]) -> Optional[uuid.UUID]:
        """
        Convert string to UUID, handling both valid UUIDs and arbitrary strings.
        For non-UUID strings, generates a deterministic UUID from the string hash.
        """
        if not value:
            return None
        try:
            return uuid.UUID(value)
        except (ValueError, AttributeError):
            # Generate deterministic UUID from string using namespace UUID
            return uuid.uuid5(uuid.NAMESPACE_DNS, value)

    def _redact_phi(self, data: Any) -> Any:
        """Redact PHI from data before logging."""
        if isinstance(data, str):
            return self.phi_redactor.redact_text(data)
        elif isinstance(data, dict):
            return self.phi_redactor.redact_dict(data)
        return data

    async def log_api_request(
        self,
        session_id: Optional[str],
        user_id: Optional[str],
        endpoint: str,
        method: str,
        status_code: int,
        latency_ms: int,
        request_category: str,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log API request for audit trail.

        Args:
            session_id: User session ID
            user_id: User ID
            endpoint: API endpoint path
            method: HTTP method (GET, POST, etc.)
            status_code: HTTP status code
            latency_ms: Request latency in milliseconds
            request_category: Category of request (diagnosis_support, chat, etc.)
            error_message: Error message if request failed (PHI redacted)
            metadata: Additional metadata (PHI redacted)
        """
        pool = await self._get_pool()

        try:
            # Redact PHI from error message and metadata
            safe_metadata = self._redact_phi(metadata) if metadata else {}

            async with pool.acquire() as conn:
                # Hash user_id for GDPR right-to-erasure compliance
                user_id_hash = DatabaseEncryption.hash_value(user_id) if user_id else None

                await conn.execute("""
                    INSERT INTO data_access_logs (
                        session_id, user_id, user_id_hash, access_type, resource_type,
                        resource_count, data_source, access_method,
                        lawful_basis, purpose_of_use,
                        access_duration_ms, access_granted, accessed_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW())
                """,
                    self._to_uuid(session_id),
                    user_id,  # Keep as string - column type is VARCHAR(255), not UUID
                    user_id_hash,  # SHA-256 hash for right-to-erasure
                    request_category,
                    "api_endpoint",
                    1,  # resource_count (1 request = 1 resource accessed)
                    "api_gateway",
                    method,
                    "legitimate_interest",  # lawful_basis - GDPR Article 6(1)(f)
                    "healthcare_delivery",  # purpose_of_use
                    latency_ms,
                    status_code < 400  # access_granted if not error
                )

                # Also log to system usage metrics
                await conn.execute("""
                    INSERT INTO system_usage_metrics (
                        metric_type, metric_name, value, unit, dimensions
                    ) VALUES ($1, $2, $3, $4, $5)
                """,
                    "api_request",
                    request_category,
                    1,
                    "count",
                    json.dumps({
                        "endpoint": endpoint,
                        "method": method,
                        "status_code": status_code,
                        "success": status_code < 400,
                        **(safe_metadata or {})
                    })
                )

        except Exception as e:
            import traceback
            log_error(logger, "Error logging API request", e)
            logger.error(f"Full traceback: {traceback.format_exc()}")
            # Don't fail the request if logging fails

    async def log_data_access(
        self,
        session_id: Optional[str],
        user_id: str,
        access_type: str,
        resource_type: str,
        resource_count: int = 1,
        data_source: str = "application",
        lawful_basis: str = "care_delivery",
        purpose_of_use: str = "clinical_decision_support",
        access_duration_ms: Optional[int] = None
    ) -> None:
        """
        Log data access for GDPR compliance.

        Args:
            session_id: Session ID
            user_id: User ID
            access_type: Type of access (read, write, delete)
            resource_type: Type of resource (patient, observation, etc.)
            resource_count: Number of resources accessed
            data_source: Source of data (fhir, database, etc.)
            lawful_basis: GDPR lawful basis
            purpose_of_use: Purpose of data access
            access_duration_ms: Duration of access in milliseconds
        """
        pool = await self._get_pool()

        try:
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO data_access_logs (
                        session_id, user_id, access_type, resource_type,
                        resource_count, data_source, lawful_basis,
                        purpose_of_use, access_duration_ms, accessed_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
                """,
                    self._to_uuid(session_id),
                    user_id,  # Keep as string - column type is VARCHAR(255), not UUID
                    access_type,
                    resource_type,
                    resource_count,
                    data_source,
                    lawful_basis,
                    purpose_of_use,
                    access_duration_ms
                )

        except Exception as e:
            log_error(logger, "Error logging data access", e)

    async def log_data_flow(
        self,
        session_id: Optional[str],
        flow_id: str,
        source_system: str,
        source_type: str,
        destination_system: str,
        destination_type: str,
        transformations: List[str],
        data_quality_score: Optional[float] = None
    ) -> None:
        """
        Log data lineage/flow for compliance tracking.

        Args:
            session_id: Session ID
            flow_id: Unique flow identifier
            source_system: Source system name
            source_type: Type of source data
            destination_system: Destination system
            destination_type: Type of destination
            transformations: List of transformations applied
            data_quality_score: Quality score (0-1)
        """
        pool = await self._get_pool()

        try:
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO data_lineage (
                        session_id, source_system, source_resource_id,
                        destination_system, destination_resource_id,
                        transformation_type, transformation_details,
                        quality_score, created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                """,
                    self._to_uuid(session_id),
                    source_system,
                    source_type,  # Use as source_resource_id
                    destination_system,
                    destination_type,  # Use as destination_resource_id
                    ', '.join(transformations) if transformations else 'none',  # Single transformation_type
                    json.dumps({"transformations": transformations, "flow_id": flow_id}),  # Details as JSONB
                    data_quality_score
                )

        except Exception as e:
            log_error(logger, "Error logging data flow", e)

    async def log_prompt_category(
        self,
        user_id: str,
        session_id: Optional[str],
        prompt_hash: str,
        category: str,
        model_used: Optional[str] = None,
        response_tokens: Optional[int] = None,
        latency_ms: Optional[int] = None
    ) -> None:
        """
        Log prompt category (NOT actual prompt content) for usage analytics.

        Args:
            user_id: User ID
            session_id: Session ID
            prompt_hash: SHA256 hash of prompt (NOT the actual prompt)
            category: Prompt category (diagnosis_support, note_generation, etc.)
            model_used: AI model used (claude-3, gpt-4, etc.)
            response_tokens: Number of tokens in response
            latency_ms: Response latency
        """
        pool = await self._get_pool()

        try:
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO system_usage_metrics (
                        metric_type, metric_name, value, unit, dimensions
                    ) VALUES ($1, $2, $3, $4, $5)
                """,
                    "prompt_usage",
                    category,
                    1,
                    "count",
                    json.dumps({
                        "user_id": user_id,
                        "session_id": session_id,
                        "prompt_hash": prompt_hash,
                        "model_used": model_used,
                        "response_tokens": response_tokens,
                        "latency_ms": latency_ms
                    })
                )

        except Exception as e:
            log_error(logger, "Error logging prompt category", e)

    async def log_compliance_event(
        self,
        event_type: str,
        compliance_framework: str,
        session_id: Optional[str],
        user_id: str,
        patient_id_hash: Optional[str] = None,
        data_categories: Optional[List[str]] = None,
        processing_purposes: Optional[List[str]] = None,
        compliance_status: str = "compliant",
        additional_context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log compliance-related events (GDPR, HIPAA, etc.).

        Args:
            event_type: Type of event (consent_recorded, data_exported, etc.)
            compliance_framework: Framework (GDPR, HIPAA)
            session_id: Session ID
            user_id: User ID
            patient_id_hash: Hash of patient ID (NOT actual ID)
            data_categories: Categories of data involved
            processing_purposes: Purposes of processing
            compliance_status: Status (compliant, violation, etc.)
            additional_context: Additional context (PHI redacted)
        """
        pool = await self._get_pool()

        try:
            safe_context = self._redact_phi(additional_context) if additional_context else {}

            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO compliance_events (
                        event_type, compliance_framework, session_id, user_id,
                        patient_id, data_categories, processing_purposes,
                        compliance_status, risk_assessment, event_timestamp
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
                """,
                    event_type,
                    compliance_framework,
                    self._to_uuid(session_id),
                    user_id,
                    patient_id_hash,
                    data_categories or [],
                    processing_purposes or [],
                    compliance_status,
                    json.dumps(safe_context)
                )

        except Exception as e:
            log_error(logger, "Error logging compliance event", e)

    async def log_usage_metric(
        self,
        metric_type: str,
        metric_name: str,
        value: int,
        unit: str = "count",
        dimensions: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None
    ) -> None:
        """
        Log system usage metric.

        Args:
            metric_type: Type of metric (api_request, llm_usage, etc.)
            metric_name: Metric name
            value: Metric value
            unit: Unit of measurement
            dimensions: Additional dimensions (PHI redacted)
            tenant_id: Tenant ID
        """
        pool = await self._get_pool()

        try:
            safe_dimensions = self._redact_phi(dimensions) if dimensions else {}

            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO system_usage_metrics (
                        metric_type, metric_name, value, unit, dimensions, tenant_id
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                """,
                    metric_type,
                    metric_name,
                    value,
                    unit,
                    json.dumps(safe_dimensions),
                    self._to_uuid(tenant_id)
                )

        except Exception as e:
            log_error(logger, "Error logging usage metric", e)

    async def log_audit_event(
        self,
        session_id: Optional[str],
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        outcome: str = "success",
        latency_ms: Optional[int] = None,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log audit event for every data operation (GDPR Article 30 compliance).

        Tracks actions like FETCH, RANK, SYNTHESIZE, CLASSIFY, etc.

        Args:
            session_id: Session ID
            action: Action performed (FETCH_CHUNKS, CLASSIFY_QUERY, SYNTHESIZE_SBAR, etc.)
            resource_type: Type of resource (chunk, patient, observation, etc.)
            resource_id: ID of resource (optional)
            outcome: Outcome of action (success, failure, partial)
            latency_ms: Duration of action in milliseconds
            user_id: User ID (optional)
            metadata: Additional metadata (PHI redacted)
        """
        pool = await self._get_pool()

        try:
            safe_metadata = self._redact_phi(metadata) if metadata else {}

            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO audit_events (
                        session_id, user_id, action, resource_type, resource_id,
                        outcome, latency_ms, metadata, occurred_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                """,
                    self._to_uuid(session_id),
                    user_id,
                    action,
                    resource_type,
                    resource_id,
                    outcome,
                    latency_ms,
                    json.dumps(safe_metadata)
                )

        except Exception as e:
            log_error(logger, f"Error logging audit event '{action}'", e)

    async def log_evidence_set(
        self,
        session_id: str,
        question_id: str,
        rank: int,
        resource_type: str,
        resource_id: Optional[str] = None,
        section: Optional[str] = None,
        rerank_score: Optional[float] = None,
        reason: Optional[str] = None,
        chunk_text_preview: Optional[str] = None
    ) -> None:
        """
        Log evidence set for retrieval provenance tracking.

        Tracks which chunks/resources were used as evidence for each query.

        Args:
            session_id: Session ID
            question_id: Unique ID for this query
            rank: Rank of this evidence in results (1-based)
            resource_type: Type of resource (chunk, document, observation)
            resource_id: ID of resource
            section: Section of document (if applicable)
            rerank_score: Cross-encoder rerank score
            reason: Reason for selection (e.g., "cross_encoder_reranked")
            chunk_text_preview: Preview of chunk text (first 200 chars, PHI redacted)
        """
        pool = await self._get_pool()

        try:
            # Redact PHI from chunk preview
            safe_preview = self._redact_phi(chunk_text_preview) if chunk_text_preview else None

            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO evidence_sets (
                        session_id, question_id, rank, resource_type, resource_id,
                        section, rerank_score, reason, chunk_text_preview, created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
                """,
                    self._to_uuid(session_id),
                    self._to_uuid(question_id),
                    rank,
                    resource_type,
                    resource_id,
                    section,
                    rerank_score,
                    reason,
                    safe_preview
                )

        except Exception as e:
            log_error(logger, f"Error logging evidence set for question {question_id}", e)

    async def log_performance_metric(
        self,
        metric_category: str,
        metric_name: str,
        value: float,
        unit: str = "milliseconds",
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        endpoint: Optional[str] = None,
        model_used: Optional[str] = None,
        processing_stage: Optional[str] = None,
        patient_context_size: Optional[int] = None,
        additional_context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log performance metric for monitoring and optimization.

        Args:
            metric_category: Category (retrieval, synthesis, llm_call, api)
            metric_name: Metric name (chunk_retrieval_time, llm_generation_time, etc.)
            value: Metric value
            unit: Unit (milliseconds, count, bytes, etc.)
            session_id: Session ID
            user_id: User ID
            endpoint: API endpoint
            model_used: AI model used
            processing_stage: Processing stage (intelligent_retrieve, generate_response, etc.)
            patient_context_size: Number of chunks/resources in context
            additional_context: Additional context (PHI redacted)
        """
        pool = await self._get_pool()

        try:
            safe_context = self._redact_phi(additional_context) if additional_context else {}

            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO performance_metrics (
                        metric_category, metric_name, value, unit, endpoint,
                        user_id, session_id, patient_context_size, model_used,
                        processing_stage, additional_context, measured_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW())
                """,
                    metric_category,
                    metric_name,
                    value,
                    unit,
                    endpoint,
                    self._to_uuid(user_id) if user_id else None,
                    self._to_uuid(session_id) if session_id else None,
                    patient_context_size,
                    model_used,
                    processing_stage,
                    json.dumps(safe_context)
                )

        except Exception as e:
            log_error(logger, f"Error logging performance metric '{metric_name}'", e)

    async def get_user_audit_trail(
        self,
        user_id: str,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get audit trail for a user (admin function).

        Returns GDPR-safe audit logs without PHI.
        """
        pool = await self._get_pool()

        try:
            async with pool.acquire() as conn:
                query = """
                    SELECT
                        access_type, resource_type, data_source,
                        lawful_basis, purpose_of_use, accessed_at
                    FROM data_access_logs
                    WHERE user_id = $1
                """
                params: list[Any] = [user_id]

                if from_date:
                    query += " AND accessed_at >= $2"
                    params.append(from_date)

                if to_date:
                    param_num = len(params) + 1
                    query += f" AND accessed_at <= ${param_num}"
                    params.append(to_date)

                query += f" ORDER BY accessed_at DESC LIMIT ${len(params) + 1}"
                params.append(limit)

                rows = await conn.fetch(query, *params)

                return [dict(row) for row in rows]

        except Exception as e:
            log_error(logger, "Error getting user audit trail", e)
            return []


# Global audit repository instance
_audit_repository: Optional[PGAuditRepository] = None


def get_audit_repository(dsn: Optional[str] = None) -> PGAuditRepository:
    """Get global audit repository instance."""
    global _audit_repository
    if _audit_repository is None:
        import os
        dsn = dsn or os.getenv("PGVECTOR_DSN") or os.getenv("DATABASE_URL")
        if not dsn:
            raise ValueError("Database DSN not configured")
        _audit_repository = PGAuditRepository(dsn)
    return _audit_repository
