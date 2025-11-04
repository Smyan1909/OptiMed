import asyncio, os, asyncpg
from pathlib import Path
from dotenv import load_dotenv

async def run():
    load_dotenv()
    conn = await asyncpg.connect(os.getenv('PGVECTOR_DSN'))
    print('Running migration 015...')
    await conn.execute(Path('migrations/015_fix_session_analytics_varchar.sql').read_text())
    print('[OK] Migration 015 completed - session_analytics now uses VARCHAR')
    await conn.close()

asyncio.run(run())