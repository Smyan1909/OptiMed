"""
Integration tests for session analytics functionality.

Tests that session_analytics table is correctly populated and updated.
"""
import pytest
import uuid
from datetime import datetime, timezone
from optimed.adapters.user_repository.pg_user_repository import PGUserRepository
from optimed.core.domain import UserSession


@pytest.mark.asyncio
async def test_initialize_session_analytics(test_db_dsn):
    """Test that session analytics is initialized on session creation."""
    repo = PGUserRepository(dsn=test_db_dsn)

    try:
        # Create test user and session
        user_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())

        # Initialize session analytics
        await repo.initialize_session_analytics(session_id, user_id)

        # Verify it was created in database
        pool = await repo._get_pool()
        async with pool.acquire() as conn:
            result = await conn.fetchrow("""
                SELECT * FROM session_analytics WHERE session_id = $1
            """, uuid.UUID(session_id))

            assert result is not None, "Session analytics row should exist"
            assert str(result['user_id']) == user_id
            assert result['total_requests'] == 0
            assert result['chat_requests'] == 0
            assert result['diagnostic_requests'] == 0
            assert result['journal_generations'] == 0
            assert result['image_uploads'] == 0
            assert result['error_count'] == 0
            assert result['session_duration_minutes'] == 0

    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_update_session_analytics(test_db_dsn):
    """Test that session analytics is updated correctly."""
    repo = PGUserRepository(dsn=test_db_dsn)

    try:
        user_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())

        # Initialize
        await repo.initialize_session_analytics(session_id, user_id)

        # Update with chat request
        await repo.update_session_analytics(
            session_id=session_id,
            requests=1,
            chat_requests=1
        )

        # Verify update
        pool = await repo._get_pool()
        async with pool.acquire() as conn:
            result = await conn.fetchrow("""
                SELECT * FROM session_analytics WHERE session_id = $1
            """, uuid.UUID(session_id))

            assert result['total_requests'] == 1
            assert result['chat_requests'] == 1
            assert result['diagnostic_requests'] == 0

        # Update with diagnostic request
        await repo.update_session_analytics(
            session_id=session_id,
            requests=1,
            diagnostic_requests=1
        )

        # Verify both updates
        async with pool.acquire() as conn:
            result = await conn.fetchrow("""
                SELECT * FROM session_analytics WHERE session_id = $1
            """, uuid.UUID(session_id))

            assert result['total_requests'] == 2
            assert result['chat_requests'] == 1
            assert result['diagnostic_requests'] == 1

    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_finalize_session_analytics(test_db_dsn):
    """Test that session analytics is finalized on session end."""
    repo = PGUserRepository(dsn=test_db_dsn)

    try:
        user_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())

        # Create session in sessions table first
        pool = await repo._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO sessions (session_id, user_id, started_at, is_active)
                VALUES ($1, $2, $3, TRUE)
            """, uuid.UUID(session_id), uuid.UUID(user_id), datetime.now(timezone.utc))

        # Initialize analytics
        await repo.initialize_session_analytics(session_id, user_id)

        # Finalize session
        await repo.finalize_session_analytics(session_id)

        # Verify ended_at is set and duration is calculated
        async with pool.acquire() as conn:
            session_result = await conn.fetchrow("""
                SELECT * FROM sessions WHERE session_id = $1
            """, uuid.UUID(session_id))

            analytics_result = await conn.fetchrow("""
                SELECT * FROM session_analytics WHERE session_id = $1
            """, uuid.UUID(session_id))

            assert session_result['ended_at'] is not None, "Session should have ended_at"
            assert analytics_result['session_duration_minutes'] > 0, "Duration should be calculated"

    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_session_analytics_multiple_updates(test_db_dsn):
    """Test that multiple updates accumulate correctly."""
    repo = PGUserRepository(dsn=test_db_dsn)

    try:
        user_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())

        await repo.initialize_session_analytics(session_id, user_id)

        # Simulate multiple requests
        for _ in range(5):
            await repo.update_session_analytics(
                session_id=session_id,
                requests=1,
                chat_requests=1
            )

        for _ in range(3):
            await repo.update_session_analytics(
                session_id=session_id,
                requests=1,
                diagnostic_requests=1
            )

        # Verify accumulated counts
        pool = await repo._get_pool()
        async with pool.acquire() as conn:
            result = await conn.fetchrow("""
                SELECT * FROM session_analytics WHERE session_id = $1
            """, uuid.UUID(session_id))

            assert result['total_requests'] == 8  # 5 + 3
            assert result['chat_requests'] == 5
            assert result['diagnostic_requests'] == 3

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
