import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def check_schema():
    dsn = os.getenv("PGVECTOR_DSN") or os.getenv("DATABASE_URL")
    conn = await asyncpg.connect(dsn)

    print("=== data_access_logs columns ===")
    rows = await conn.fetch("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'data_access_logs'
        ORDER BY ordinal_position
    """)
    for r in rows:
        nullable = "NULL" if r['is_nullable'] == 'YES' else "NOT NULL"
        print(f"  {r['column_name']}: {r['data_type']} ({nullable})")

    print("\n=== data_lineage columns ===")
    rows = await conn.fetch("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'data_lineage'
        ORDER BY ordinal_position
    """)
    for r in rows:
        nullable = "NULL" if r['is_nullable'] == 'YES' else "NOT NULL"
        print(f"  {r['column_name']}: {r['data_type']} ({nullable})")

    await conn.close()

if __name__ == "__main__":
    asyncio.run(check_schema())
