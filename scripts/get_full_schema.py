"""
Get complete database schema overview
"""
import asyncio
import asyncpg
import os
from dotenv import load_dotenv


async def get_schema():
    """Get complete schema overview."""
    load_dotenv()

    dsn = os.getenv("PGVECTOR_DSN") or os.getenv("DATABASE_URL")
    conn = await asyncpg.connect(dsn)

    try:
        # Get all tables
        print("=" * 80)
        print("DATABASE SCHEMA OVERVIEW")
        print("=" * 80)

        tables = await conn.fetch("""
            SELECT
                table_name,
                obj_description(('"' || table_schema || '"."' || table_name || '"')::regclass) as table_comment
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)

        print(f"\nTotal Tables: {len(tables)}\n")

        for table in tables:
            table_name = table['table_name']
            comment = table['table_comment'] or 'No description'

            print(f"\n{'=' * 80}")
            print(f"TABLE: {table_name}")
            print(f"Description: {comment}")
            print(f"{'=' * 80}")

            # Get columns
            columns = await conn.fetch("""
                SELECT
                    column_name,
                    data_type,
                    is_nullable,
                    column_default,
                    character_maximum_length
                FROM information_schema.columns
                WHERE table_name = $1
                ORDER BY ordinal_position
            """, table_name)

            print("\nColumns:")
            for col in columns:
                nullable = "NULL" if col['is_nullable'] == 'YES' else "NOT NULL"
                default = f" DEFAULT {col['column_default']}" if col['column_default'] else ""
                max_len = f"({col['character_maximum_length']})" if col['character_maximum_length'] else ""
                print(f"  • {col['column_name']}: {col['data_type']}{max_len} {nullable}{default}")

            # Get indexes
            indexes = await conn.fetch("""
                SELECT
                    indexname,
                    indexdef
                FROM pg_indexes
                WHERE tablename = $1
                ORDER BY indexname
            """, table_name)

            if indexes:
                print("\nIndexes:")
                for idx in indexes:
                    print(f"  • {idx['indexname']}")

            # Get foreign keys
            fks = await conn.fetch("""
                SELECT
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
                    AND tc.table_name = $1
            """, table_name)

            if fks:
                print("\nForeign Keys:")
                for fk in fks:
                    print(f"  • {fk['column_name']} -> {fk['foreign_table_name']}.{fk['foreign_column_name']}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(get_schema())
