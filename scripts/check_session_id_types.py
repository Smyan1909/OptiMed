"""
Check which tables have session_id columns and their data types.
"""
import asyncio
import asyncpg
import os
import sys
from dotenv import load_dotenv

load_dotenv()

async def check_session_id_types():
    dsn = os.getenv('PGVECTOR_DSN')
    if not dsn:
        print('ERROR: PGVECTOR_DSN environment variable not set')
        sys.exit(1)

    try:
        conn = await asyncpg.connect(dsn)

        # Check all tables with session_id column
        results = await conn.fetch('''
            SELECT table_name, column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE column_name = 'session_id'
            ORDER BY table_name
        ''')

        print('\n' + '='*80)
        print('TABLES WITH session_id COLUMN')
        print('='*80)

        uuid_tables = []
        varchar_tables = []

        for row in results:
            table = row['table_name']
            dtype = row['data_type']
            nullable = row['is_nullable']

            status = '✓ VARCHAR' if dtype == 'character varying' else '✗ UUID'
            print(f"{status:15} {table:30} {dtype:20} nullable={nullable}")

            if dtype == 'uuid':
                uuid_tables.append(table)
            else:
                varchar_tables.append(table)

        print('\n' + '='*80)
        print('SUMMARY')
        print('='*80)
        print(f"Tables with VARCHAR session_id: {len(varchar_tables)}")
        print(f"Tables with UUID session_id:    {len(uuid_tables)}")

        if uuid_tables:
            print('\n⚠️  WARNING: The following tables still have UUID session_id:')
            for table in uuid_tables:
                print(f"  - {table}")
            print('\nMigration 017 may not have run successfully!')
        else:
            print('\n✓ All tables have been migrated to VARCHAR session_id')

        await conn.close()

    except Exception as e:
        print(f'ERROR: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    asyncio.run(check_session_id_types())
