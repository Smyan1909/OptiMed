#!/usr/bin/env python3
"""
Fix migration status for already-applied migrations.
This updates the tracking table when objects already exist but migration is marked as failed.
"""
import asyncio
import os
from pathlib import Path
import asyncpg
from dotenv import load_dotenv


async def fix_migration_status():
    """Fix migration tracking status."""
    print("=" * 60)
    print("Fixing Migration Status")
    print("=" * 60)

    # Load environment
    load_dotenv()

    # Get database DSN
    dsn = os.getenv("PGVECTOR_DSN")
    if not dsn:
        print("\n❌ PGVECTOR_DSN environment variable not set")
        return False

    print(f"\nUsing database: {dsn.split('@')[1] if '@' in dsn else 'configured'}")

    try:
        # Connect to database
        print("\nConnecting to database...")
        conn = await asyncpg.connect(dsn)
        print("Connected successfully")

        # Read SQL file
        sql_file = Path("scripts/fix_migration_status.sql")
        if not sql_file.exists():
            print(f"\nSQL file not found: {sql_file}")
            return False

        # Execute the fix
        print("\nUpdating migration status...")

        # Update migration 003
        await conn.execute("""
            UPDATE schema_migrations
            SET
                success = TRUE,
                applied_at = NOW(),
                error_message = NULL
            WHERE migration_name = '003_create_rls_policies'
        """)
        print("[OK] Updated 003_create_rls_policies")

        # Update migration 006
        await conn.execute("""
            UPDATE schema_migrations
            SET
                success = TRUE,
                applied_at = NOW(),
                error_message = NULL
            WHERE migration_name = '006_create_note_templates_and_audit'
        """)
        print("[OK] Updated 006_create_note_templates_and_audit")

        # Verify the fix
        print("\nVerifying updates...")
        rows = await conn.fetch("""
            SELECT
                migration_name,
                success,
                applied_at,
                error_message
            FROM schema_migrations
            WHERE migration_name IN ('003_create_rls_policies', '006_create_note_templates_and_audit')
            ORDER BY migration_name
        """)

        for row in rows:
            status = "[OK]" if row['success'] else "[FAIL]"
            print(f"  {status} {row['migration_name']}: {row['applied_at'].strftime('%Y-%m-%d %H:%M:%S')}")
            if row['error_message']:
                print(f"      Error: {row['error_message']}")

        # Show overall migration status
        print("\nOverall Migration Status:")
        all_migrations = await conn.fetch("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
                SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as failed
            FROM schema_migrations
        """)

        stats = all_migrations[0]
        print(f"  Total: {stats['total']}")
        print(f"  Successful: {stats['successful']}")
        print(f"  Failed: {stats['failed']}")

        await conn.close()

        if stats['failed'] == 0:
            print("\n" + "=" * 60)
            print("SUCCESS: All migrations are now marked as successful!")
            print("=" * 60)
            return True
        else:
            print("\nWARNING: Some migrations still showing as failed")
            return False

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(fix_migration_status())
    exit(0 if success else 1)
