#!/usr/bin/env python3
"""
Azure PostgreSQL Database Viewer
Interactive tool to explore tables and data in optimed-db-sweden
"""

import asyncpg
import asyncio
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

class DatabaseViewer:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.conn: asyncpg.Connection = None

    async def connect(self):
        """Connect to Azure PostgreSQL."""
        print("[INFO] Connecting to Azure PostgreSQL...")
        self.conn = await asyncpg.connect(self.dsn)
        print("[OK] Connected successfully\n")

    async def close(self):
        """Close connection."""
        if self.conn:
            await self.conn.close()

    async def list_all_tables(self):
        """List all tables in the database."""
        print("="*70)
        print("ALL TABLES IN DATABASE")
        print("="*70)

        tables = await self.conn.fetch("""
            SELECT
                table_name,
                (SELECT COUNT(*)
                 FROM information_schema.columns
                 WHERE columns.table_name = tables.table_name) as column_count
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)

        if not tables:
            print("[WARN] No tables found")
            return []

        table_names = []
        for i, table in enumerate(tables, 1):
            table_names.append(table['table_name'])
            print(f"{i:2d}. {table['table_name']:30s} ({table['column_count']} columns)")

        return table_names

    async def describe_table(self, table_name: str):
        """Show table structure."""
        print("\n" + "="*70)
        print(f"TABLE STRUCTURE: {table_name}")
        print("="*70)

        columns = await self.conn.fetch("""
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_name = $1
            ORDER BY ordinal_position
        """, table_name)

        if not columns:
            print(f"[ERROR] Table '{table_name}' not found")
            return

        print(f"{'Column':<30s} {'Type':<20s} {'Nullable':<10s} {'Default'}")
        print("-"*70)
        for col in columns:
            default = str(col['column_default'])[:20] if col['column_default'] else ''
            print(f"{col['column_name']:<30s} {col['data_type']:<20s} {col['is_nullable']:<10s} {default}")

        # Get row count
        try:
            count = await self.conn.fetchval(f"SELECT COUNT(*) FROM {table_name}")
            print(f"\nTotal rows: {count:,}")
        except Exception as e:
            print(f"\n[WARN] Could not count rows: {e}")

    async def view_table_data(self, table_name: str, limit: int = 10):
        """View recent data from a table."""
        print("\n" + "="*70)
        print(f"TABLE DATA: {table_name} (last {limit} rows)")
        print("="*70)

        try:
            # Get time-based column for ordering
            time_col = None
            for col_name in ['accessed_at', 'created_at', 'recorded_at', 'occurred_at', 'started_at']:
                has_col = await self.conn.fetchval(f"""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns
                        WHERE table_name = $1 AND column_name = $2
                    )
                """, table_name, col_name)
                if has_col:
                    time_col = col_name
                    break

            # Build query
            if time_col:
                query = f"SELECT * FROM {table_name} ORDER BY {time_col} DESC LIMIT $1"
            else:
                query = f"SELECT * FROM {table_name} LIMIT $1"

            rows = await self.conn.fetch(query, limit)

            if not rows:
                print("[INFO] No data found")
                return

            # Print data
            for i, row in enumerate(rows, 1):
                print(f"\n--- Row {i} ---")
                for key, value in row.items():
                    if isinstance(value, datetime):
                        value = value.strftime('%Y-%m-%d %H:%M:%S')
                    elif isinstance(value, bytes):
                        value = f"<binary: {len(value)} bytes>"
                    elif isinstance(value, dict):
                        value = str(value)[:100]
                    elif isinstance(value, list):
                        value = str(value)[:100]
                    print(f"  {key:25s}: {value}")

        except Exception as e:
            print(f"[ERROR] Could not fetch data: {e}")

    async def view_audit_summary(self):
        """Show audit logging summary."""
        print("\n" + "="*70)
        print("AUDIT LOGGING SUMMARY")
        print("="*70)

        # Check if data_access_logs exists
        has_audit = await self.conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'data_access_logs'
            )
        """)

        if not has_audit:
            print("[WARN] data_access_logs table not found")
            return

        # Total audit logs
        total = await self.conn.fetchval("SELECT COUNT(*) FROM data_access_logs")
        print(f"\nTotal audit logs: {total:,}")

        # By access type
        print("\nBy Access Type:")
        access_types = await self.conn.fetch("""
            SELECT access_type, COUNT(*) as count
            FROM data_access_logs
            GROUP BY access_type
            ORDER BY count DESC
        """)
        for row in access_types:
            print(f"  {row['access_type']:20s}: {row['count']:,}")

        # Recent activity (last 24 hours)
        recent = await self.conn.fetchval("""
            SELECT COUNT(*) FROM data_access_logs
            WHERE accessed_at > NOW() - INTERVAL '24 hours'
        """)
        print(f"\nLast 24 hours: {recent:,}")

        # Errors (access_granted = false)
        errors = await self.conn.fetchval("""
            SELECT COUNT(*) FROM data_access_logs
            WHERE access_granted = false
        """)
        print(f"Failed accesses: {errors:,}")

        # Recent errors
        if errors > 0:
            print("\nRecent Failed Accesses:")
            error_rows = await self.conn.fetch("""
                SELECT accessed_at, user_id, access_type, resource_type
                FROM data_access_logs
                WHERE access_granted = false
                ORDER BY accessed_at DESC
                LIMIT 5
            """)
            for row in error_rows:
                print(f"  {row['accessed_at'].strftime('%Y-%m-%d %H:%M:%S')} - "
                      f"User: {row['user_id']}, Type: {row['access_type']}, "
                      f"Resource: {row['resource_type']}")

    async def check_foreign_keys(self):
        """Check foreign key constraints."""
        print("\n" + "="*70)
        print("FOREIGN KEY CONSTRAINTS")
        print("="*70)

        fk_constraints = await self.conn.fetch("""
            SELECT
                tc.table_name,
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name,
                tc.constraint_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
            ORDER BY tc.table_name, kcu.column_name
        """)

        if not fk_constraints:
            print("[INFO] No foreign key constraints found")
            return

        print(f"\nTotal foreign keys: {len(fk_constraints)}\n")
        for fk in fk_constraints:
            print(f"{fk['table_name']}.{fk['column_name']} -> "
                  f"{fk['foreign_table_name']}.{fk['foreign_column_name']}")
            print(f"  Constraint: {fk['constraint_name']}\n")

    async def interactive_mode(self):
        """Interactive exploration mode."""
        await self.connect()

        while True:
            print("\n" + "="*70)
            print("AZURE DATABASE VIEWER - INTERACTIVE MODE")
            print("="*70)
            print("\nOptions:")
            print("  1. List all tables")
            print("  2. Describe table structure")
            print("  3. View table data")
            print("  4. View audit logging summary")
            print("  5. Check foreign key constraints")
            print("  6. Run custom SQL query")
            print("  0. Exit")

            choice = input("\nEnter choice: ").strip()

            if choice == "0":
                print("\nExiting...")
                break
            elif choice == "1":
                await self.list_all_tables()
            elif choice == "2":
                table_names = await self.list_all_tables()
                table = input("\nEnter table name: ").strip()
                if table in table_names:
                    await self.describe_table(table)
                else:
                    print(f"[ERROR] Table '{table}' not found")
            elif choice == "3":
                table_names = await self.list_all_tables()
                table = input("\nEnter table name: ").strip()
                if table in table_names:
                    limit = input("Number of rows to show (default 10): ").strip()
                    limit = int(limit) if limit.isdigit() else 10
                    await self.view_table_data(table, limit)
                else:
                    print(f"[ERROR] Table '{table}' not found")
            elif choice == "4":
                await self.view_audit_summary()
            elif choice == "5":
                await self.check_foreign_keys()
            elif choice == "6":
                query = input("\nEnter SQL query: ").strip()
                try:
                    result = await self.conn.fetch(query)
                    if result:
                        for i, row in enumerate(result, 1):
                            print(f"\nRow {i}:")
                            for key, value in row.items():
                                print(f"  {key}: {value}")
                    else:
                        print("[INFO] No results")
                except Exception as e:
                    print(f"[ERROR] Query failed: {e}")
            else:
                print("[ERROR] Invalid choice")

        await self.close()

    async def quick_overview(self):
        """Show quick database overview and exit."""
        await self.connect()

        # List tables
        table_names = await self.list_all_tables()

        # Show audit summary
        await self.view_audit_summary()

        # Show foreign keys
        await self.check_foreign_keys()

        # Show recent data_access_logs
        print("\n" + "="*70)
        print("RECENT AUDIT LOGS (Last 5)")
        print("="*70)
        if 'data_access_logs' in table_names:
            await self.view_table_data('data_access_logs', 5)

        await self.close()


async def main():
    """Main entry point."""
    import sys

    # Get database connection string
    dsn = os.getenv("PGVECTOR_DSN") or os.getenv("DATABASE_URL")

    if not dsn:
        print("[ERROR] PGVECTOR_DSN or DATABASE_URL environment variable not set")
        print("\nPlease set it to your Azure PostgreSQL connection string:")
        print("  set PGVECTOR_DSN=postgresql://user:password@optimed-db-sweden.postgres.database.azure.com:5432/optimed")
        return False

    viewer = DatabaseViewer(dsn)

    # Check for command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == "--overview":
            await viewer.quick_overview()
        elif sys.argv[1] == "--table" and len(sys.argv) > 2:
            await viewer.connect()
            await viewer.describe_table(sys.argv[2])
            if len(sys.argv) > 3 and sys.argv[3] == "--data":
                limit = int(sys.argv[4]) if len(sys.argv) > 4 else 10
                await viewer.view_table_data(sys.argv[2], limit)
            await viewer.close()
        else:
            print("Usage:")
            print("  python view_azure_database.py                    # Interactive mode")
            print("  python view_azure_database.py --overview         # Quick overview")
            print("  python view_azure_database.py --table <name>     # Describe table")
            print("  python view_azure_database.py --table <name> --data [limit]  # View data")
    else:
        # Interactive mode
        await viewer.interactive_mode()


if __name__ == "__main__":
    asyncio.run(main())
