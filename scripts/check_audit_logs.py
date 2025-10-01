"""
Script to check audit logging status in the database.

Usage:
    python scripts/check_audit_logs.py
"""

import os
import asyncio
import asyncpg
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

def print_table(data, headers):
    """Simple table printer without external dependencies."""
    if not data:
        return

    # Calculate column widths
    col_widths = [len(h) for h in headers]
    for row in data:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))

    # Print header
    header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    print(header_line)
    print("-" * len(header_line))

    # Print rows
    for row in data:
        print(" | ".join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row)))

async def check_audit_tables():
    """Check if audit tables exist and show record counts."""

    dsn = os.getenv("PGVECTOR_DSN") or os.getenv("DATABASE_URL")
    if not dsn:
        print("[X] Error: PGVECTOR_DSN or DATABASE_URL not found in environment")
        return

    print(f"[*] Connecting to database...")

    try:
        conn = await asyncpg.connect(dsn)

        # Check which audit tables exist
        print("\n[*] Checking audit tables...")
        audit_tables = [
            'data_access_logs',
            'system_usage_metrics',
            'data_lineage',
            'audit_events',
            'compliance_events',
            'performance_metrics',
            'encryption_audit_log'
        ]

        existing_tables = []
        for table in audit_tables:
            result = await conn.fetchval(
                "SELECT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = $1)",
                table
            )
            if result:
                existing_tables.append(table)

        if existing_tables:
            print(f"[OK] Found {len(existing_tables)} audit tables:")
            for table in existing_tables:
                print(f"   - {table}")
        else:
            print("[X] No audit tables found! Run migrations first.")
            await conn.close()
            return

        # Get record counts for each existing table
        print("\n[*] Record counts and latest activity:")
        table_stats = []

        for table in existing_tables:
            try:
                # Get count
                count = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")

                # Get latest timestamp (different column names per table)
                timestamp_col = None
                if table == 'data_access_logs':
                    timestamp_col = 'accessed_at'
                elif table == 'system_usage_metrics':
                    timestamp_col = 'recorded_at'
                elif table == 'data_lineage':
                    timestamp_col = 'created_at'
                elif table in ['audit_events', 'compliance_events']:
                    timestamp_col = 'created_at'
                elif table == 'performance_metrics':
                    timestamp_col = 'measured_at'
                elif table == 'encryption_audit_log':
                    timestamp_col = 'operation_timestamp'

                latest = None
                if timestamp_col:
                    try:
                        latest = await conn.fetchval(f"SELECT MAX({timestamp_col}) FROM {table}")
                    except:
                        latest = "N/A"

                table_stats.append([
                    table,
                    count,
                    str(latest) if latest else "No records"
                ])
            except Exception as e:
                table_stats.append([table, "Error", str(e)])

        print_table(table_stats, ["Table", "Records", "Latest Activity"])

        # Show recent API requests
        if 'data_access_logs' in existing_tables:
            print("\n[*] Recent API requests (last 10):")
            rows = await conn.fetch("""
                SELECT
                    accessed_at,
                    user_id,
                    access_type,
                    resource_type,
                    data_source,
                    resource_count,
                    access_duration_ms,
                    CASE WHEN access_granted THEN '[OK]' ELSE '[X]' END as granted
                FROM data_access_logs
                ORDER BY accessed_at DESC
                LIMIT 10
            """)

            if rows:
                data = [[
                    r['accessed_at'].strftime('%H:%M:%S'),
                    str(r['user_id'])[:8] + '...' if r['user_id'] else 'None',
                    r['access_type'],
                    r['resource_type'] or 'N/A',
                    r['data_source'] or 'N/A',
                    r['resource_count'] or 0,
                    r['access_duration_ms'] or 'N/A',
                    r['granted']
                ] for r in rows]

                print_table(data, ["Time", "User", "Type", "Resource", "Source", "Count", "Duration (ms)", "Status"])
            else:
                print("   No API requests logged yet")

        # Show recent usage metrics
        if 'system_usage_metrics' in existing_tables:
            print("\n[*] Recent usage metrics (last 10):")
            rows = await conn.fetch("""
                SELECT
                    recorded_at,
                    metric_type,
                    metric_name,
                    value,
                    unit,
                    dimensions
                FROM system_usage_metrics
                ORDER BY recorded_at DESC
                LIMIT 10
            """)

            if rows:
                import json
                data = []
                for r in rows:
                    time_str = r['recorded_at'].strftime('%H:%M:%S') if r['recorded_at'] else 'N/A'
                    dims = json.loads(r['dimensions']) if r['dimensions'] else {}
                    # Show first dimension value if exists
                    dim_str = list(dims.values())[0] if dims else 'N/A'
                    if isinstance(dim_str, str) and len(dim_str) > 20:
                        dim_str = dim_str[:20] + '...'

                    data.append([
                        time_str,
                        r['metric_type'],
                        r['metric_name'],
                        r['value'],
                        r['unit'],
                        str(dim_str)
                    ])

                print_table(data, ["Time", "Type", "Metric", "Value", "Unit", "Context"])
            else:
                print("   No usage metrics logged yet")

        # Show recent data lineage
        if 'data_lineage' in existing_tables:
            print("\n[*] Recent data lineage (last 10):")
            rows = await conn.fetch("""
                SELECT
                    created_at,
                    source_system,
                    source_resource_id,
                    destination_system,
                    destination_resource_id,
                    transformation_type,
                    quality_score
                FROM data_lineage
                ORDER BY created_at DESC
                LIMIT 10
            """)

            if rows:
                data = [[
                    r['created_at'].strftime('%H:%M:%S'),
                    r['source_system'],
                    r['source_resource_id'][:15] + '...' if r['source_resource_id'] and len(r['source_resource_id']) > 15 else r['source_resource_id'],
                    r['destination_system'],
                    r['destination_resource_id'][:15] + '...' if r['destination_resource_id'] and len(r['destination_resource_id']) > 15 else r['destination_resource_id'],
                    r['transformation_type'][:20] + '...' if r['transformation_type'] and len(r['transformation_type']) > 20 else r['transformation_type'],
                    f"{r['quality_score']:.2f}" if r['quality_score'] else 'N/A'
                ] for r in rows]

                print_table(data, ["Time", "Source", "Src ID", "Dest", "Dest ID", "Transform", "Quality"])
            else:
                print("   No data lineage logged yet")

        await conn.close()
        print("\n[OK] Audit check complete!")

    except Exception as e:
        print(f"[X] Error connecting to database: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(check_audit_tables())
