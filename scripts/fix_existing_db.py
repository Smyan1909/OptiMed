#!/usr/bin/env python3
"""
Fix Existing Local Database

Manually fixes schema issues in the existing database without dropping it.
"""

import os
import sys
import psycopg2
from dotenv import load_dotenv

def fix_database():
    load_dotenv()

    db_user = os.getenv('POSTGRES_USER', 'optimed_user')
    db_password = os.getenv('POSTGRES_PASSWORD', 'test_user')
    db_name = os.getenv('POSTGRES_DB', 'optimed')
    db_host = os.getenv('POSTGRESS_HOST', 'localhost')
    db_port = os.getenv('POSTGRES_PORT', '5432')

    print("=" * 60)
    print("  Fix Existing Local Database")
    print("=" * 60)
    print()
    print(f"Database: {db_host}:{db_port}/{db_name}")
    print(f"User: {db_user}")
    print()

    # Read SQL file (v3)
    sql_file_path = os.path.join(os.path.dirname(__file__), 'fix_existing_db_v3.sql')

    with open(sql_file_path, 'r') as f:
        sql_script = f.read()

    print("Connecting to database...")
    print("This will drop conflicting tables and reset failed migrations...")
    print("(Comprehensive cleanup to match production schema)")

    try:
        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_password,
            database=db_name
        )

        print("Connected successfully!")
        print()
        print("Executing schema fixes...")
        print()

        cursor = conn.cursor()

        # Execute the SQL script
        cursor.execute(sql_script)

        # Fetch and print the success message
        try:
            result = cursor.fetchone()
            if result:
                print(result[0])
        except:
            pass

        conn.commit()
        cursor.close()
        conn.close()

        print()
        print("=" * 60)
        print("Schema fixed successfully!")
        print("=" * 60)
        print()
        print("Next step: Run migrations")
        print("  python scripts/run_migrations.py")
        print()

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    fix_database()
