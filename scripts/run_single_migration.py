"""
Run a single migration file
"""
import asyncio
import asyncpg
import os
import sys
from dotenv import load_dotenv

async def run_migration(migration_file: str):
    """Run a single migration file."""
    # Load environment variables
    load_dotenv()

    # Get database connection string
    dsn = os.getenv("PGVECTOR_DSN") or os.getenv("DATABASE_URL")
    if not dsn:
        print("Error: PGVECTOR_DSN or DATABASE_URL not set")
        sys.exit(1)

    # Read migration file
    with open(migration_file, 'r', encoding='utf-8') as f:
        sql = f.read()

    # Connect and execute
    conn = await asyncpg.connect(dsn)
    try:
        print(f"Running migration: {migration_file}")
        await conn.execute(sql)
        print("Migration completed successfully!")
    except Exception as e:
        print(f"Error running migration: {e}")
        raise
    finally:
        await conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_single_migration.py <migration_file>")
        sys.exit(1)

    migration_file = sys.argv[1]
    asyncio.run(run_migration(migration_file))
