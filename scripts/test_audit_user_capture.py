"""
Test script to verify that user IDs are being properly captured in audit logs.
"""
import asyncio
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from optimed.adapters.audit.audit_repository import PGAuditRepository


async def test_user_capture():
    """Verify user IDs are captured in recent audit logs."""

    print("=" * 80)
    print("USER ID CAPTURE VERIFICATION TEST")
    print("=" * 80)
    print()

    # Initialize audit repository
    audit_repo = PGAuditRepository(os.getenv("PGVECTOR_DSN"))
    pool = await audit_repo._get_pool()

    # Check data_access_logs for user_id population
    print("1. Checking data_access_logs table...")
    print("-" * 80)

    query_access = """
        SELECT
            COUNT(*) as total_logs,
            COUNT(user_id) as logs_with_user_id,
            COUNT(*) - COUNT(user_id) as logs_without_user_id,
            ROUND(COUNT(user_id)::numeric / NULLIF(COUNT(*), 0) * 100, 2) as user_id_percentage
        FROM data_access_logs
        WHERE accessed_at >= NOW() - INTERVAL '24 hours'
    """

    result = await pool.fetchrow(query_access)
    print(f"  Total logs (last 24h): {result['total_logs']}")
    print(f"  Logs WITH user_id: {result['logs_with_user_id']}")
    print(f"  Logs WITHOUT user_id: {result['logs_without_user_id']}")
    print(f"  User ID capture rate: {result['user_id_percentage']}%")
    print()

    # Check compliance_events for user_id population
    print("2. Checking compliance_events table...")
    print("-" * 80)

    query_compliance = """
        SELECT
            COUNT(*) as total_events,
            COUNT(user_id) as events_with_user_id,
            COUNT(*) - COUNT(user_id) as events_without_user_id,
            ROUND(COUNT(user_id)::numeric / NULLIF(COUNT(*), 0) * 100, 2) as user_id_percentage
        FROM compliance_events
        WHERE occurred_at >= NOW() - INTERVAL '24 hours'
    """

    result = await pool.fetchrow(query_compliance)
    print(f"  Total events (last 24h): {result['total_events']}")
    print(f"  Events WITH user_id: {result['events_with_user_id']}")
    print(f"  Events WITHOUT user_id: {result['events_without_user_id']}")
    print(f"  User ID capture rate: {result['user_id_percentage']}%")
    print()

    # Show sample of recent audit logs with user IDs
    print("3. Recent audit logs with user IDs (sample)...")
    print("-" * 80)

    query_sample = """
        SELECT
            accessed_at,
            user_id,
            access_type,
            resource_type,
            data_source
        FROM data_access_logs
        WHERE user_id IS NOT NULL
        ORDER BY accessed_at DESC
        LIMIT 5
    """

    rows = await pool.fetch(query_sample)
    if rows:
        for row in rows:
            print(f"  [{row['accessed_at']}] User: {row['user_id']}")
            print(f"    Access: {row['access_type']} | Resource: {row['resource_type']} | Source: {row['data_source']}")
    else:
        print("  No audit logs with user_id found")
    print()

    # Show sample of recent compliance events with user IDs
    print("4. Recent compliance events with user IDs (sample)...")
    print("-" * 80)

    query_compliance_sample = """
        SELECT
            occurred_at,
            user_id,
            event_type,
            compliance_framework,
            compliance_status
        FROM compliance_events
        WHERE user_id IS NOT NULL
        ORDER BY occurred_at DESC
        LIMIT 5
    """

    rows = await pool.fetch(query_compliance_sample)
    if rows:
        for row in rows:
            print(f"  [{row['occurred_at']}] User: {row['user_id']}")
            print(f"    Event: {row['event_type']} | Framework: {row['compliance_framework']} | Status: {row['compliance_status']}")
    else:
        print("  No compliance events with user_id found")
    print()

    # Check for encryption audit logs
    print("5. Checking encryption audit logs...")
    print("-" * 80)

    query_encryption = """
        SELECT
            COUNT(*) as total_encryption_events,
            COUNT(DISTINCT operation_type) as operation_types
        FROM encryption_audit_log
        WHERE performed_at >= NOW() - INTERVAL '24 hours'
    """

    result = await pool.fetchrow(query_encryption)
    print(f"  Total encryption events (last 24h): {result['total_encryption_events']}")
    print(f"  Distinct operation types: {result['operation_types']}")
    print()

    # Check for usage metrics
    print("6. Checking system usage metrics...")
    print("-" * 80)

    query_usage = """
        SELECT
            metric_type,
            COUNT(*) as count
        FROM system_usage_metrics
        WHERE recorded_at >= NOW() - INTERVAL '24 hours'
        GROUP BY metric_type
        ORDER BY count DESC
        LIMIT 5
    """

    rows = await pool.fetch(query_usage)
    if rows:
        for row in rows:
            print(f"  {row['metric_type']}: {row['count']} events")
    else:
        print("  No usage metrics found")
    print()

    print("=" * 80)
    print("VERIFICATION COMPLETE")
    print("=" * 80)

    await audit_repo.close()


if __name__ == "__main__":
    asyncio.run(test_user_capture())
