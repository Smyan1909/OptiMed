#!/usr/bin/env python3
"""
Complete Database Schema Report Generator
Generates a comprehensive report of all tables, columns, and sample data
"""

import asyncpg
import asyncio
import os
from datetime import datetime
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

class SchemaReporter:
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

    async def get_all_tables(self) -> List[str]:
        """Get list of all tables."""
        tables = await self.conn.fetch("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)
        return [t['table_name'] for t in tables]

    async def get_table_info(self, table_name: str) -> Dict[str, Any]:
        """Get detailed info about a table."""
        # Get columns
        columns = await self.conn.fetch("""
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

        # Get row count
        try:
            row_count = await self.conn.fetchval(f"SELECT COUNT(*) FROM {table_name}")
        except Exception:
            row_count = 0

        # Get primary key
        pk = await self.conn.fetch("""
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
            WHERE tc.table_name = $1
            AND tc.constraint_type = 'PRIMARY KEY'
        """, table_name)

        # Get foreign keys
        fks = await self.conn.fetch("""
            SELECT
                kcu.column_name,
                ccu.table_name AS foreign_table,
                ccu.column_name AS foreign_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name
            WHERE tc.table_name = $1
            AND tc.constraint_type = 'FOREIGN KEY'
        """, table_name)

        # Get indexes
        indexes = await self.conn.fetch("""
            SELECT
                indexname,
                indexdef
            FROM pg_indexes
            WHERE tablename = $1
            AND indexname NOT LIKE '%_pkey'
        """, table_name)

        # Get sample data (first 3 rows)
        sample_data = []
        try:
            # Find time column for ordering
            time_col = None
            for col in columns:
                col_name = col['column_name']
                if any(x in col_name for x in ['created_at', 'accessed_at', 'recorded_at', 'started_at']):
                    time_col = col_name
                    break

            if time_col:
                query = f"SELECT * FROM {table_name} ORDER BY {time_col} DESC LIMIT 3"
            else:
                query = f"SELECT * FROM {table_name} LIMIT 3"

            sample_data = await self.conn.fetch(query)
        except Exception as e:
            print(f"[WARN] Could not fetch sample data for {table_name}: {e}")

        return {
            'columns': columns,
            'row_count': row_count,
            'primary_keys': [pk_row['column_name'] for pk_row in pk],
            'foreign_keys': fks,
            'indexes': indexes,
            'sample_data': sample_data
        }

    def format_value(self, value: Any) -> str:
        """Format a value for display."""
        if value is None:
            return "NULL"
        elif isinstance(value, datetime):
            return value.strftime('%Y-%m-%d %H:%M:%S')
        elif isinstance(value, bytes):
            return f"<binary:{len(value)}bytes>"
        elif isinstance(value, (dict, list)):
            s = str(value)
            return s[:50] + "..." if len(s) > 50 else s
        elif isinstance(value, str):
            return value[:50] + "..." if len(value) > 50 else value
        else:
            return str(value)

    async def generate_report(self, output_file: str = None):
        """Generate complete schema report."""
        await self.connect()

        tables = await self.get_all_tables()

        report_lines = []

        # Header
        report_lines.append("="*100)
        report_lines.append("COMPLETE DATABASE SCHEMA REPORT")
        report_lines.append("Database: optimed-db-sweden")
        report_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append("="*100)
        report_lines.append(f"\nTotal Tables: {len(tables)}\n")

        # Table of contents
        report_lines.append("\nTABLE OF CONTENTS")
        report_lines.append("-"*100)
        for i, table in enumerate(tables, 1):
            info = await self.get_table_info(table)
            report_lines.append(f"{i:2d}. {table:40s} ({info['row_count']:,} rows, {len(info['columns'])} columns)")
        report_lines.append("")

        # Detailed table information
        for table_num, table_name in enumerate(tables, 1):
            print(f"[INFO] Processing table {table_num}/{len(tables)}: {table_name}")

            info = await self.get_table_info(table_name)

            report_lines.append("\n" + "="*100)
            report_lines.append(f"TABLE {table_num}: {table_name.upper()}")
            report_lines.append("="*100)

            # Basic info
            report_lines.append(f"\nRow Count: {info['row_count']:,}")
            report_lines.append(f"Total Columns: {len(info['columns'])}")

            # Primary keys
            if info['primary_keys']:
                report_lines.append(f"Primary Key: {', '.join(info['primary_keys'])}")

            # Foreign keys
            if info['foreign_keys']:
                report_lines.append("\nForeign Keys:")
                for fk in info['foreign_keys']:
                    report_lines.append(f"  - {fk['column_name']} -> {fk['foreign_table']}.{fk['foreign_column']}")

            # Indexes
            if info['indexes']:
                report_lines.append(f"\nIndexes: {len(info['indexes'])}")
                for idx in info['indexes']:
                    report_lines.append(f"  - {idx['indexname']}")

            # Column details
            report_lines.append("\nCOLUMNS:")
            report_lines.append("-"*100)
            report_lines.append(f"{'Column Name':<35s} {'Type':<25s} {'Nullable':<10s} {'Default'}")
            report_lines.append("-"*100)

            for col in info['columns']:
                col_name = col['column_name']

                # Mark special columns
                if col_name in info['primary_keys']:
                    col_name = f"{col_name} (PK)"

                # Data type with length
                data_type = col['data_type']
                if col['character_maximum_length']:
                    data_type = f"{data_type}({col['character_maximum_length']})"

                # Default value
                default = str(col['column_default'])[:30] if col['column_default'] else ""

                report_lines.append(
                    f"{col_name:<35s} {data_type:<25s} {col['is_nullable']:<10s} {default}"
                )

            # Sample data
            if info['sample_data']:
                report_lines.append(f"\nSAMPLE DATA (First {len(info['sample_data'])} rows):")
                report_lines.append("-"*100)

                for row_num, row in enumerate(info['sample_data'], 1):
                    report_lines.append(f"\nRow {row_num}:")
                    for key, value in row.items():
                        formatted_value = self.format_value(value)
                        report_lines.append(f"  {key:<33s}: {formatted_value}")
            else:
                report_lines.append("\nSAMPLE DATA: (No data in table)")

            report_lines.append("")

        # Summary statistics
        report_lines.append("\n" + "="*100)
        report_lines.append("SUMMARY STATISTICS")
        report_lines.append("="*100)

        total_rows = 0
        tables_with_data = 0
        empty_tables = []

        for table in tables:
            info = await self.get_table_info(table)
            total_rows += info['row_count']
            if info['row_count'] > 0:
                tables_with_data += 1
            else:
                empty_tables.append(table)

        report_lines.append(f"\nTotal Tables: {len(tables)}")
        report_lines.append(f"Tables with Data: {tables_with_data}")
        report_lines.append(f"Empty Tables: {len(empty_tables)}")
        report_lines.append(f"Total Rows (all tables): {total_rows:,}")

        if empty_tables:
            report_lines.append("\nEmpty Tables:")
            for table in empty_tables:
                report_lines.append(f"  - {table}")

        # Check for audit logging health
        report_lines.append("\n" + "="*100)
        report_lines.append("AUDIT LOGGING HEALTH CHECK")
        report_lines.append("="*100)

        audit_tables = ['data_access_logs', 'audit_events', 'compliance_events', 'data_lineage']
        for audit_table in audit_tables:
            if audit_table in tables:
                info = await self.get_table_info(audit_table)
                status = "[OK]" if info['row_count'] > 0 else "[EMPTY]"
                report_lines.append(f"{status} {audit_table:30s}: {info['row_count']:,} entries")

                # Check for recent activity (last 24 hours)
                try:
                    recent = await self.conn.fetchval(f"""
                        SELECT COUNT(*) FROM {audit_table}
                        WHERE (accessed_at > NOW() - INTERVAL '24 hours'
                            OR created_at > NOW() - INTERVAL '24 hours'
                            OR recorded_at > NOW() - INTERVAL '24 hours'
                            OR occurred_at > NOW() - INTERVAL '24 hours')
                    """)
                    if recent:
                        report_lines.append(f"      Last 24h: {recent:,} entries")
                except Exception:
                    pass
            else:
                report_lines.append(f"[MISSING] {audit_table}")

        # Database constraints check
        report_lines.append("\n" + "="*100)
        report_lines.append("CONSTRAINT VERIFICATION")
        report_lines.append("="*100)

        # Check for problematic FK constraints
        problematic_fks = await self.conn.fetch("""
            SELECT
                tc.table_name,
                kcu.column_name,
                tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
            AND tc.table_name IN ('data_access_logs', 'data_lineage', 'audit_events')
            AND kcu.column_name = 'session_id'
        """)

        if problematic_fks:
            report_lines.append(f"\n[WARN] Found {len(problematic_fks)} potentially problematic FK constraints on session_id:")
            for fk in problematic_fks:
                report_lines.append(f"  - {fk['table_name']}.{fk['column_name']}: {fk['constraint_name']}")
        else:
            report_lines.append("\n[OK] No problematic session_id foreign key constraints found")

        # Check nullable columns
        report_lines.append("\nNullable Status Check:")
        critical_cols = [
            ('data_access_logs', 'user_id'),
            ('data_access_logs', 'session_id'),
            ('compliance_events', 'user_id'),
        ]

        for table, column in critical_cols:
            if table in tables:
                nullable = await self.conn.fetchval("""
                    SELECT is_nullable FROM information_schema.columns
                    WHERE table_name = $1 AND column_name = $2
                """, table, column)
                status = "[OK]" if nullable == 'YES' else "[ISSUE]"
                report_lines.append(f"{status} {table}.{column}: nullable={nullable}")

        await self.close()

        # Output report
        report_text = "\n".join(report_lines)

        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(report_text)
            print(f"\n[OK] Report saved to: {output_file}")

        print("\n" + report_text)

        return report_text


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

    reporter = SchemaReporter(dsn)

    # Determine output file
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = f"database_schema_report_{timestamp}.txt"

    if len(sys.argv) > 1:
        output_file = sys.argv[1]

    print("="*100)
    print("DATABASE SCHEMA REPORT GENERATOR")
    print("="*100)
    print("\nGenerating comprehensive schema report...")
    print(f"Output file: {output_file}\n")

    await reporter.generate_report(output_file)

    print("\n[OK] Report generation complete!")
    print(f"[OK] Report saved to: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
