#!/usr/bin/env python3
"""Check what tables exist in the database"""

import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()

db_user = os.getenv('POSTGRES_USER', 'optimed_user')
db_password = os.getenv('POSTGRES_PASSWORD', 'test_user')
db_name = os.getenv('POSTGRES_DB', 'optimed')
db_host = os.getenv('POSTGRESS_HOST', 'localhost')
db_port = os.getenv('POSTGRES_PORT', '5432')

conn = psycopg2.connect(
    host=db_host,
    port=db_port,
    user=db_user,
    password=db_password,
    database=db_name
)

cursor = conn.cursor()

# List all tables
cursor.execute("""
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public'
    AND table_type = 'BASE TABLE'
    ORDER BY table_name;
""")

tables = cursor.fetchall()

print("\nCurrent tables in database:")
print("=" * 60)
for (table,) in tables:
    # Get column count
    cursor.execute(f"""
        SELECT COUNT(*)
        FROM information_schema.columns
        WHERE table_name = '{table}';
    """)
    col_count = cursor.fetchone()[0]
    print(f"  {table:40s} ({col_count} columns)")

# Check gdpr_requests specifically
print("\n" + "=" * 60)
print("gdpr_requests table schema:")
print("=" * 60)
cursor.execute("""
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns
    WHERE table_name = 'gdpr_requests'
    ORDER BY ordinal_position;
""")

cols = cursor.fetchall()
if cols:
    for col_name, data_type, is_nullable in cols:
        print(f"  {col_name:30s} {data_type:20s} NULL={is_nullable}")
else:
    print("  Table does not exist")

cursor.close()
conn.close()
