"""
Integration tests for audit events functionality.

Tests that audit_events, evidence_sets, and performance_metrics tables are populated.
"""
import pytest
import uuid
from optimed.adapters.audit.audit_repository import PGAuditRepository


@pytest.mark.asyncio
async def test_log_audit_event(test_db_dsn):
    """Test that audit events are logged correctly."""
    repo = PGAuditRepository(dsn=test_db_dsn)

    try:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())

        # Log an audit event
        await repo.log_audit_event(
            session_id=session_id,
            action="FETCH_CHUNKS_COMPLETE",
            resource_type="chunk",
            outcome="success",
            latency_ms=500,
            user_id=user_id,
            metadata={"chunks_retrieved": 10, "total_chunks": 50}
        )

        # Verify it was logged
        pool = await repo._get_pool()
        async with pool.acquire() as conn:
            result = await conn.fetchrow("""
                SELECT * FROM audit_events
                WHERE session_id = $1 AND action = $2
                ORDER BY occurred_at DESC LIMIT 1
            """, uuid.UUID(session_id), "FETCH_CHUNKS_COMPLETE")

            assert result is not None, "Audit event should be logged"
            assert result['action'] == "FETCH_CHUNKS_COMPLETE"
            assert result['resource_type'] == "chunk"
            assert result['outcome'] == "success"
            assert result['latency_ms'] == 500
            assert result['user_id'] == user_id

    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_log_multiple_audit_events(test_db_dsn):
    """Test that multiple audit events are logged in sequence."""
    repo = PGAuditRepository(dsn=test_db_dsn)

    try:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())

        # Log sequence of events
        actions = [
            "CLASSIFY_QUERY",
            "FETCH_CHUNKS_START",
            "FETCH_CHUNKS_COMPLETE",
            "GENERATE_RESPONSE"
        ]

        for action in actions:
            await repo.log_audit_event(
                session_id=session_id,
                action=action,
                resource_type="query" if "CLASSIFY" in action else "chunk",
                outcome="success",
                user_id=user_id
            )

        # Verify all events were logged
        pool = await repo._get_pool()
        async with pool.acquire() as conn:
            results = await conn.fetch("""
                SELECT action FROM audit_events
                WHERE session_id = $1
                ORDER BY occurred_at ASC
            """, uuid.UUID(session_id))

            logged_actions = [r['action'] for r in results]
            assert logged_actions == actions, "All audit events should be logged in order"

    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_log_evidence_set(test_db_dsn):
    """Test that evidence sets are logged correctly."""
    repo = PGAuditRepository(dsn=test_db_dsn)

    try:
        session_id = str(uuid.uuid4())
        question_id = str(uuid.uuid4())

        # Log evidence set
        await repo.log_evidence_set(
            session_id=session_id,
            question_id=question_id,
            rank=1,
            resource_type="chunk",
            resource_id="chunk_123",
            rerank_score=0.95,
            reason="cross_encoder_reranked",
            chunk_text_preview="This is a preview of the chunk content..."
        )

        # Verify it was logged
        pool = await repo._get_pool()
        async with pool.acquire() as conn:
            result = await conn.fetchrow("""
                SELECT * FROM evidence_sets
                WHERE session_id = $1 AND question_id = $2 AND rank = $3
            """, uuid.UUID(session_id), uuid.UUID(question_id), 1)

            assert result is not None, "Evidence set should be logged"
            assert result['resource_type'] == "chunk"
            assert result['resource_id'] == "chunk_123"
            assert result['rerank_score'] == pytest.approx(0.95, rel=1e-2)
            assert result['reason'] == "cross_encoder_reranked"

    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_log_multiple_evidence_sets(test_db_dsn):
    """Test logging multiple evidence sets for a single query."""
    repo = PGAuditRepository(dsn=test_db_dsn)

    try:
        session_id = str(uuid.uuid4())
        question_id = str(uuid.uuid4())

        # Log multiple evidence sets (simulating top-5 chunks)
        for rank in range(1, 6):
            await repo.log_evidence_set(
                session_id=session_id,
                question_id=question_id,
                rank=rank,
                resource_type="chunk",
                resource_id=f"chunk_{rank}",
                rerank_score=1.0 - (rank * 0.1),  # Descending scores
                reason="cross_encoder_reranked"
            )

        # Verify all were logged
        pool = await repo._get_pool()
        async with pool.acquire() as conn:
            results = await conn.fetch("""
                SELECT rank, resource_id, rerank_score FROM evidence_sets
                WHERE session_id = $1 AND question_id = $2
                ORDER BY rank ASC
            """, uuid.UUID(session_id), uuid.UUID(question_id))

            assert len(results) == 5, "Should have 5 evidence sets"
            for i, result in enumerate(results, start=1):
                assert result['rank'] == i
                assert result['resource_id'] == f"chunk_{i}"
                assert result['rerank_score'] == pytest.approx(1.0 - (i * 0.1), rel=1e-2)

    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_log_performance_metric(test_db_dsn):
    """Test that performance metrics are logged correctly."""
    repo = PGAuditRepository(dsn=test_db_dsn)

    try:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())

        # Log performance metric
        await repo.log_performance_metric(
            metric_category="retrieval",
            metric_name="total_retrieval_time",
            value=450.5,
            unit="milliseconds",
            session_id=session_id,
            user_id=user_id,
            processing_stage="intelligent_retrieve_chunks",
            patient_context_size=15
        )

        # Verify it was logged
        pool = await repo._get_pool()
        async with pool.acquire() as conn:
            result = await conn.fetchrow("""
                SELECT * FROM performance_metrics
                WHERE session_id = $1 AND metric_name = $2
                ORDER BY measured_at DESC LIMIT 1
            """, uuid.UUID(session_id), "total_retrieval_time")

            assert result is not None, "Performance metric should be logged"
            assert result['metric_category'] == "retrieval"
            assert result['metric_name'] == "total_retrieval_time"
            assert result['value'] == pytest.approx(450.5, rel=1e-2)
            assert result['unit'] == "milliseconds"
            assert result['processing_stage'] == "intelligent_retrieve_chunks"
            assert result['patient_context_size'] == 15

    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_log_multiple_performance_metrics(test_db_dsn):
    """Test logging multiple performance metrics for different stages."""
    repo = PGAuditRepository(dsn=test_db_dsn)

    try:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())

        metrics = [
            ("retrieval", "total_retrieval_time", 450.0, "milliseconds"),
            ("retrieval", "chunks_retrieved_count", 15.0, "count"),
            ("synthesis", "llm_generation_time", 1200.0, "milliseconds"),
            ("synthesis", "token_count", 500.0, "count")
        ]

        for category, name, value, unit in metrics:
            await repo.log_performance_metric(
                metric_category=category,
                metric_name=name,
                value=value,
                unit=unit,
                session_id=session_id,
                user_id=user_id
            )

        # Verify all metrics were logged
        pool = await repo._get_pool()
        async with pool.acquire() as conn:
            results = await conn.fetch("""
                SELECT metric_category, metric_name, value, unit
                FROM performance_metrics
                WHERE session_id = $1
                ORDER BY measured_at ASC
            """, uuid.UUID(session_id))

            assert len(results) == 4, "Should have 4 performance metrics"
            for i, (category, name, value, unit) in enumerate(metrics):
                assert results[i]['metric_category'] == category
                assert results[i]['metric_name'] == name
                assert results[i]['value'] == pytest.approx(value, rel=1e-2)
                assert results[i]['unit'] == unit

    finally:
        await repo.close()


# Pytest fixture for test database DSN
@pytest.fixture
def test_db_dsn():
    """Provide test database DSN from environment."""
    import os
    dsn = os.getenv("TEST_PGVECTOR_DSN") or os.getenv("PGVECTOR_DSN")
    if not dsn:
        pytest.skip("No test database configured")
    return dsn
