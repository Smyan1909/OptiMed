#!/usr/bin/env python3
"""
Reset Local Development Database

This script drops and recreates the local OptiMed database,
then runs all migrations from scratch. Safe for local dev only.

DO NOT USE ON PRODUCTION!
"""

import os
import sys
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

def reset_database():
    """Drop and recreate the local database"""

    load_dotenv()

    # Get connection details
    db_user = os.getenv('POSTGRES_USER', 'optimed_user')
    db_password = os.getenv('POSTGRES_PASSWORD', 'test_user')
    db_name = os.getenv('POSTGRES_DB', 'optimed')
    db_host = os.getenv('POSTGRESS_HOST', 'localhost')  # Note: typo in .env
    db_port = os.getenv('POSTGRES_PORT', '5432')

    print("=" * 60)
    print("🔄 OptiMed Local Database Reset")
    print("=" * 60)
    print()
    print(f"⚠️  WARNING: This will DROP the database '{db_name}'")
    print(f"   Host: {db_host}:{db_port}")
    print(f"   User: {db_user}")
    print()

    # Safety check - ensure this is localhost
    if db_host not in ['localhost', '127.0.0.1', '::1']:
        print("❌ ERROR: This script is for LOCAL databases only!")
        print(f"   Host '{db_host}' is not localhost")
        print("   Refusing to continue for safety.")
        sys.exit(1)

    # Confirmation prompt
    response = input("Type 'yes' to continue: ")
    if response.lower() != 'yes':
        print("❌ Aborted.")
        sys.exit(0)

    print()
    print("🔌 Connecting to PostgreSQL server...")

    try:
        # Connect to postgres database (default)
        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_password,
            database='postgres'
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()

        print("✅ Connected to PostgreSQL")
        print()

        # Terminate existing connections to the database
        print(f"🔌 Terminating existing connections to '{db_name}'...")
        cursor.execute(f"""
            SELECT pg_terminate_backend(pg_stat_activity.pid)
            FROM pg_stat_activity
            WHERE pg_stat_activity.datname = '{db_name}'
              AND pid <> pg_backend_pid();
        """)

        # Drop the database
        print(f"🗑️  Dropping database '{db_name}'...")
        cursor.execute(f"DROP DATABASE IF EXISTS {db_name};")
        print("✅ Database dropped")
        print()

        # Create fresh database
        print(f"🆕 Creating fresh database '{db_name}'...")
        cursor.execute(f"CREATE DATABASE {db_name};")
        print("✅ Database created")
        print()

        cursor.close()
        conn.close()

        # Connect to new database to enable extensions
        print("🔌 Connecting to new database...")
        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_password,
            database=db_name
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()

        # Enable required extensions
        print("🔧 Enabling PostgreSQL extensions...")
        extensions = [
            ('vector', 'pgvector for embeddings'),
            ('pgcrypto', 'cryptographic functions')
        ]

        for ext_name, ext_desc in extensions:
            try:
                cursor.execute(f"CREATE EXTENSION IF NOT EXISTS {ext_name};")
                print(f"  ✅ {ext_name} - {ext_desc}")
            except Exception as e:
                print(f"  ⚠️  {ext_name} - {str(e)}")

        cursor.close()
        conn.close()

        print()
        print("=" * 60)
        print("✅ Database reset complete!")
        print("=" * 60)
        print()
        print("Next step: Run migrations")
        print("  python scripts/run_migrations.py")
        print()

    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    reset_database()
