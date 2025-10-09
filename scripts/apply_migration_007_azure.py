#!/usr/bin/env python3
"""
Apply migration 007 to Azure PostgreSQL (optimed-db-sweden)
Fixes the NOT NULL constraint on data_access_logs.user_id
"""

import asyncpg
import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

async def apply_migration():
    """Apply migration 007 to Azure PostgreSQL."""

    # Get Azure PostgreSQL connection string
    dsn = os.getenv("PGVECTOR_DSN") or os.getenv("DATABASE_URL")

    if not dsn:
        print("[ERROR] PGVECTOR_DSN or DATABASE_URL environment variable not set")
        print("\nPlease set it to your Azure PostgreSQL connection string:")
        print("  export PGVECTOR_DSN='postgresql://user:password@optimed-db-sweden.postgres.database.azure.com:5432/optimed'")
        return False

    print(f"[INFO] Connecting to Azure PostgreSQL...")

    try:
        # Connect to database
        conn = await asyncpg.connect(dsn)
        print("[OK] Connected successfully")

        # Check current constraint status
        print("\n[INFO] Checking current user_id constraint...")
        constraint_check = await conn.fetchrow("""
            SELECT
                column_name,
                is_nullable,
                data_type
            FROM information_schema.columns
            WHERE table_name = 'data_access_logs'
            AND column_name = 'user_id'
        """)

        if constraint_check:
            print(f"   Current status: {constraint_check['column_name']} - "
                  f"Nullable: {constraint_check['is_nullable']}, "
                  f"Type: {constraint_check['data_type']}")
        else:
            print("[WARN] data_access_logs table or user_id column not found")

        # Read migration file
        migration_path = Path(__file__).parent.parent / "migrations" / "007_fix_audit_user_id_nullable.sql"

        if not migration_path.exists():
            print(f"[ERROR] Migration file not found at {migration_path}")
            return False

        with open(migration_path, 'r') as f:
            migration_sql = f.read()

        print(f"\n[INFO] Applying migration 007...")
        print("   SQL: ALTER TABLE data_access_logs ALTER COLUMN user_id DROP NOT NULL")

        # Apply migration
        await conn.execute(migration_sql)

        print("[OK] Migration applied successfully!")

        # Verify the change
        print("\n[INFO] Verifying constraint was removed...")
        new_status = await conn.fetchrow("""
            SELECT
                column_name,
                is_nullable
            FROM information_schema.columns
            WHERE table_name = 'data_access_logs'
            AND column_name = 'user_id'
        """)

        if new_status and new_status['is_nullable'] == 'YES':
            print(f"[OK] Success! user_id is now nullable: {new_status['is_nullable']}")
        else:
            print(f"[WARN] Unexpected status: {new_status}")

        await conn.close()
        print("\n[OK] Migration complete! You can now restart your Azure Container App.")
        return True

    except asyncpg.exceptions.DuplicateObjectError as e:
        print(f"[WARN] Migration already applied (duplicate): {e}")
        return True

    except Exception as e:
        print(f"\n[ERROR] Error applying migration: {e}")
        import traceback
        print(traceback.format_exc())
        return False


if __name__ == "__main__":
    print("=" * 70)
    print("  Azure PostgreSQL Migration 007 - Fix user_id nullable constraint")
    print("=" * 70)

    success = asyncio.run(apply_migration())

    if success:
        print("\n[OK] All done! Next steps:")
        print("   1. Restart the Azure Container App:")
        print("      az containerapp revision restart \\")
        print("        --name optimed-api-sweden \\")
        print("        --resource-group OPTIMED")
        print("\n   2. Test by chatting about a patient")
    else:
        print("\n[ERROR] Migration failed. Please check the error messages above.")
        exit(1)
