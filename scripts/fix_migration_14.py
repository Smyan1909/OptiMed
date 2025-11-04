import asyncio, os, asyncpg
from pathlib import Path
from dotenv import load_dotenv

async def run():
    load_dotenv()
    conn = await asyncpg.connect(os.getenv('PGVECTOR_DSN'))
    print('Running migration 014...')
    await conn.execute(Path('migrations/014_add_missing_columns.sql').read_text())
    print('[OK] Migration 014 completed')
    await conn.close()

asyncio.run(run())