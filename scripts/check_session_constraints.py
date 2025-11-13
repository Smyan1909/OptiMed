"""
Check for triggers and foreign keys that might cause VARCHAR=UUID comparison errors.
"""
import asyncio
import asyncpg
import os
import sys
from dotenv import load_dotenv

load_dotenv()

async def check_constraints():
    dsn = os.getenv('PGVECTOR_DSN')
    if not dsn:
        print('ERROR: PGVECTOR_DSN environment variable not set')
        sys.exit(1)

    try:
        conn = await asyncpg.connect(dsn)

        print('\n' + '='*80)
        print('TRIGGERS ON SESSIONS-RELATED TABLES')
        print('='*80)

        triggers = await conn.fetch('''
            SELECT
                event_object_table as table_name,
                trigger_name,
                event_manipulation,
                action_statement
            FROM information_schema.triggers
            WHERE event_object_table IN ('sessions', 'session_analytics', 'audit_events',
                                         'data_access_logs', 'performance_metrics', 'evidence_sets')
            ORDER BY event_object_table, trigger_name
        ''')

        if triggers:
            for t in triggers:
                print(f"\n{t['table_name']}.{t['trigger_name']}")
                print(f"  Event: {t['event_manipulation']}")
                print(f"  Action: {t['action_statement'][:100]}...")
        else:
            print("No triggers found")

        print('\n' + '='*80)
        print('FOREIGN KEYS REFERENCING sessions.session_id')
        print('='*80)

        fkeys = await conn.fetch('''
            SELECT
                tc.table_name,
                tc.constraint_name,
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
              ON ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND ccu.table_name = 'sessions'
              AND ccu.column_name = 'session_id'
            ORDER BY tc.table_name
        ''')

        if fkeys:
            for fk in fkeys:
                print(f"\n{fk['table_name']}.{fk['column_name']}")
                print(f"  Constraint: {fk['constraint_name']}")
                print(f"  References: {fk['foreign_table_name']}.{fk['foreign_column_name']}")

                # Check the data type of the referencing column
                col_type = await conn.fetchval('''
                    SELECT data_type
                    FROM information_schema.columns
                    WHERE table_name = $1 AND column_name = $2
                ''', fk['table_name'], fk['column_name'])

                status = "⚠️  TYPE MISMATCH" if col_type != 'uuid' else "✓ OK"
                print(f"  Type: {col_type} {status}")
        else:
            print("No foreign keys found (all have been dropped)")

        print('\n' + '='*80)
        print('RLS POLICIES ON sessions TABLE')
        print('='*80)

        policies = await conn.fetch('''
            SELECT policyname, cmd, qual, with_check
            FROM pg_policies
            WHERE tablename = 'sessions'
            ORDER BY policyname
        ''')

        if policies:
            for p in policies:
                print(f"\n{p['policyname']}")
                print(f"  Command: {p['cmd']}")
                if p['qual']:
                    print(f"  USING: {p['qual']}")
                if p['with_check']:
                    print(f"  WITH CHECK: {p['with_check']}")
        else:
            print("No RLS policies found")

        await conn.close()

    except Exception as e:
        print(f'ERROR: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    asyncio.run(check_constraints())
