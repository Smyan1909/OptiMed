"""
Verify that audit table foreign key constraints are removed
"""
import asyncio
import asyncpg
import os
from dotenv import load_dotenv


async def verify_fix():
    """Verify the foreign key constraints are removed."""
    load_dotenv()

    dsn = os.getenv("PGVECTOR_DSN") or os.getenv("DATABASE_URL")
    conn = await asyncpg.connect(dsn)

    try:
        # Check foreign key constraints
        print("=== Checking foreign key constraints on audit tables ===")
        fk_constraints = await conn.fetch("""
            SELECT
                tc.table_name,
                kcu.column_name,
                ccu.table_name AS foreign_table
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_name IN ('data_lineage', 'data_access_logs')
        """)

        if not fk_constraints:
            print("✅ No foreign key constraints found - audit logging is fixed!")
        else:
            print(f"⚠️ Still have {len(fk_constraints)} foreign key constraints:")
            for fk in fk_constraints:
                print(f"  {fk['table_name']}.{fk['column_name']} -> {fk['foreign_table']}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(verify_fix())
