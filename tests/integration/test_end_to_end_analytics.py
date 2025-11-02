"""
End-to-end integration tests for the complete analytics flow.

Tests that simulate a full user session with analytics tracking.
"""
import pytest
import uuid
from datetime import datetime, timezone
from optimed.adapters.user_repository.pg_user_repository import PGUserRepository
from optimed.adapters.audit.audit_repository import PGAuditRepository


@pytest.mark.asyncio
async def test_complete_session_lifecycle(test_db_dsn):
    """
    Test complete session lifecycle with analytics:
    1. Session creation
    2. Multiple requests (chat, diagnose, journal)
    3. Audit events logged
    4. Performance metrics tracked
    5. Session finalization
    """
    user_repo = PGUserRepository(dsn=test_db_dsn)
    audit_repo = PGAuditRepository(dsn=test_db_dsn)

    try:
        user_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())

        # Step 1: Create session
        pool = await user_repo._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO sessions (session_id, user_id, started_at, is_active)
                VALUES ($1, $2, $3, TRUE)
            """, uuid.UUID(session_id), uuid.UUID(user_id), datetime.now(timezone.utc))

        # Initialize session analytics
        await user_repo.initialize_session_analytics(session_id, user_id)

        # Step 2: Simulate chat request
        await user_repo.update_session_analytics(
            session_id=session_id,
            requests=1,
            chat_requests=1
        )

        # Log audit events for chat
        await audit_repo.log_audit_event(
            session_id=session_id,
            action="CLASSIFY_QUERY",
            resource_type="query",
            outcome="success",
            user_id=user_id
        )

        await audit_repo.log_audit_event(
            session_id=session_id,
            action="FETCH_CHUNKS_COMPLETE",
            resource_type="chunk",
            outcome="success",
            latency_ms=400,
            user_id=user_id
        )

        # Log performance metrics
        await audit_repo.log_performance_metric(
            metric_category="retrieval",
            metric_name="total_retrieval_time",
            value=400.0,
            session_id=session_id,
            user_id=user_id
        )

        # Step 3: Simulate diagnostic request
        await user_repo.update_session_analytics(
            session_id=session_id,
            requests=1,
            diagnostic_requests=1
        )

        # Step 4: Simulate journal generation
        await user_repo.update_session_analytics(
            session_id=session_id,
            requests=1,
            journal_generations=1
        )

        # Step 5: Finalize session
        await user_repo.finalize_session_analytics(session_id)

        # Verify complete data
        async with pool.acquire() as conn:
            # Check session_analytics
            analytics = await conn.fetchrow("""
                SELECT * FROM session_analytics WHERE session_id = $1
            """, uuid.UUID(session_id))

            assert analytics['total_requests'] == 3
            assert analytics['chat_requests'] == 1
            assert analytics['diagnostic_requests'] == 1
            assert analytics['journal_generations'] == 1
            assert analytics['session_duration_minutes'] > 0

            # Check audit_events
            audit_events = await conn.fetch("""
                SELECT action FROM audit_events WHERE session_id = $1
            """, uuid.UUID(session_id))

            assert len(audit_events) >= 2
            actions = [e['action'] for e in audit_events]
            assert "CLASSIFY_QUERY" in actions
            assert "FETCH_CHUNKS_COMPLETE" in actions

            # Check performance_metrics
            metrics = await conn.fetch("""
                SELECT * FROM performance_metrics WHERE session_id = $1
            """, uuid.UUID(session_id))

            assert len(metrics) >= 1
            assert metrics[0]['metric_category'] == "retrieval"

            # Check session ended
            session = await conn.fetchrow("""
                SELECT * FROM sessions WHERE session_id = $1
            """, uuid.UUID(session_id))

            assert session['ended_at'] is not None

    finally:
        await user_repo.close()
        await audit_repo.close()


@pytest.mark.asyncio
async def test_retrieval_flow_with_evidence_sets(test_db_dsn):
    """
    Test retrieval flow with complete evidence tracking:
    1. Classify query
    2. Fetch chunks
    3. Log evidence sets for selected chunks
    4. Log performance metrics
    """
    audit_repo = PGAuditRepository(dsn=test_db_dsn)

    try:
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        question_id = str(uuid.uuid4())

        # Simulate retrieval flow
        # Step 1: Classify
        await audit_repo.log_audit_event(
            session_id=session_id,
            action="CLASSIFY_QUERY",
            resource_type="query",
            outcome="success",
            latency_ms=100,
            user_id=user_id,
            metadata={"classification": "lookup"}
        )

        # Step 2: Fetch chunks
        await audit_repo.log_audit_event(
            session_id=session_id,
            action="FETCH_CHUNKS_START",
            resource_type="chunk",
            outcome="in_progress",
            user_id=user_id
        )

        # Step 3: Log evidence sets (top 5 chunks)
        for rank in range(1, 6):
            await audit_repo.log_evidence_set(
                session_id=session_id,
                question_id=question_id,
                rank=rank,
                resource_type="chunk",
                resource_id=f"chunk_{rank}",
                rerank_score=1.0 - (rank * 0.1),
                reason="cross_encoder_reranked_mmr_diversified"
            )

        # Step 4: Complete fetch
        await audit_repo.log_audit_event(
            session_id=session_id,
            action="FETCH_CHUNKS_COMPLETE",
            resource_type="chunk",
            outcome="success",
            latency_ms=450,
            user_id=user_id,
            metadata={"chunks_retrieved": 5, "total_chunks": 100}
        )

        # Step 5: Log performance metrics
        await audit_repo.log_performance_metric(
            metric_category="retrieval",
            metric_name="total_retrieval_time",
            value=450.0,
            session_id=session_id,
            user_id=user_id,
            patient_context_size=5
        )

        # Verify complete flow
        pool = await audit_repo._get_pool()
        async with pool.acquire() as conn:
            # Verify audit events
            events = await conn.fetch("""
                SELECT action, outcome FROM audit_events
                WHERE session_id = $1
                ORDER BY occurred_at ASC
            """, uuid.UUID(session_id))

            assert len(events) == 3
            assert events[0]['action'] == "CLASSIFY_QUERY"
            assert events[1]['action'] == "FETCH_CHUNKS_START"
            assert events[2]['action'] == "FETCH_CHUNKS_COMPLETE"
            assert events[2]['outcome'] == "success"

            # Verify evidence sets
            evidence = await conn.fetch("""
                SELECT rank, resource_id, rerank_score FROM evidence_sets
                WHERE session_id = $1 AND question_id = $2
                ORDER BY rank ASC
            """, uuid.UUID(session_id), uuid.UUID(question_id))

            assert len(evidence) == 5
            for i in range(5):
                assert evidence[i]['rank'] == i + 1
                assert evidence[i]['rerank_score'] == pytest.approx(1.0 - ((i + 1) * 0.1), rel=1e-2)

            # Verify performance metrics
            metrics = await conn.fetch("""
                SELECT * FROM performance_metrics WHERE session_id = $1
            """, uuid.UUID(session_id))

            assert len(metrics) == 1
            assert metrics[0]['metric_name'] == "total_retrieval_time"
            assert metrics[0]['value'] == 450.0

    finally:
        await audit_repo.close()


@pytest.mark.asyncio
async def test_error_tracking_in_session_analytics(test_db_dsn):
    """Test that errors are tracked in session analytics."""
    user_repo = PGUserRepository(dsn=test_db_dsn)

    try:
        user_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())

        await user_repo.initialize_session_analytics(session_id, user_id)

        # Simulate requests with some errors
        for _ in range(3):
            await user_repo.update_session_analytics(
                session_id=session_id,
                requests=1,
                chat_requests=1
            )

        for _ in range(2):
            await user_repo.update_session_analytics(
                session_id=session_id,
                requests=1,
                errors=1
            )

        # Verify error tracking
        pool = await user_repo._get_pool()
        async with pool.acquire() as conn:
            result = await conn.fetchrow("""
                SELECT * FROM session_analytics WHERE session_id = $1
            """, uuid.UUID(session_id))

            assert result['total_requests'] == 5
            assert result['chat_requests'] == 3
            assert result['error_count'] == 2

    finally:
        await user_repo.close()


# Pytest fixture for test database DSN
@pytest.fixture
def test_db_dsn():
    """Provide test database DSN from environment."""
    import os
    dsn = os.getenv("TEST_PGVECTOR_DSN") or os.getenv("PGVECTOR_DSN")
    if not dsn:
        pytest.skip("No test database configured")
    return dsn
