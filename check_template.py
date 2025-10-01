import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def check():
    dsn = os.getenv('PGVECTOR_DSN')
    conn = await asyncpg.connect(dsn)

    rows = await conn.fetch(
        "SELECT name, template_structure, file_format FROM note_templates WHERE name = 'Remiss';"
    )

    if rows:
        print('Remiss template found:')
        print(f"  Name: {rows[0]['name']}")
        print(f"  File format: {rows[0]['file_format']}")
        print(f"  Structure type: {type(rows[0]['template_structure'])}")
        print(f"  Structure value: {rows[0]['template_structure']}")
    else:
        print('Remiss template NOT FOUND')

    await conn.close()

asyncio.run(check())
