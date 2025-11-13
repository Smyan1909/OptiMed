#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Create New Local Development Database

This script creates a fresh OptiMed database for local development.
Attempts multiple strategies based on available permissions.
"""

import os
import sys
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from dotenv import load_dotenv

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

def print_header(title):
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)
    print()

def print_postgres_reset_instructions():
    """Instructions for resetting PostgreSQL admin password"""
    print_header("🔑 PostgreSQL Admin Password Reset Instructions")

    print("If you need to reset your PostgreSQL admin password:")
    print()
    print("METHOD 1: Using pg_ctl (if installed via PostgreSQL installer)")
    print("-" * 60)
    print("1. Find your PostgreSQL data directory:")
    print("   Common locations:")
    print("   - C:\\Program Files\\PostgreSQL\\15\\data")
    print("   - C:\\Program Files\\PostgreSQL\\14\\data")
    print()
    print("2. Edit pg_hba.conf:")
    print("   - Find: host    all    all    127.0.0.1/32    scram-sha-256")
    print("   - Change to: host    all    all    127.0.0.1/32    trust")
    print()
    print("3. Restart PostgreSQL:")
    print("   - Windows Services > PostgreSQL > Restart")
    print("   Or command: net stop postgresql-x64-15 && net start postgresql-x64-15")
    print()
    print("4. Connect without password and reset:")
    print("   psql -U postgres -d postgres")
    print("   ALTER USER postgres WITH PASSWORD 'new_password';")
    print()
    print("5. Revert pg_hba.conf back to 'scram-sha-256'")
    print()
    print("6. Restart PostgreSQL again")
    print()
    print()

    print("METHOD 2: Using Docker (if PostgreSQL is in Docker)")
    print("-" * 60)
    print("1. Access the container:")
    print("   docker exec -it <postgres-container> psql -U postgres")
    print()
    print("2. Reset password:")
    print("   ALTER USER postgres WITH PASSWORD 'new_password';")
    print()
    print()

    print("METHOD 3: Reinstall PostgreSQL")
    print("-" * 60)
    print("1. Use PostgreSQL installer to reinstall")
    print("2. Choose a new password during installation")
    print()

def create_new_database():
    """Create a new database with a fresh name"""

    load_dotenv()

    # Try different connection strategies
    strategies = [
        {
            'name': 'Current user (optimed_user)',
            'user': os.getenv('POSTGRES_USER', 'optimed_user'),
            'password': os.getenv('POSTGRES_PASSWORD', 'test_user'),
        },
        {
            'name': 'Default postgres user (no password)',
            'user': 'postgres',
            'password': '',
        },
        {
            'name': 'Default postgres user (password: postgres)',
            'user': 'postgres',
            'password': 'postgres',
        },
        {
            'name': 'Default postgres user (password: admin)',
            'user': 'postgres',
            'password': 'admin',
        },
    ]

    db_host = os.getenv('POSTGRESS_HOST', 'localhost')
    db_port = os.getenv('POSTGRES_PORT', '5432')
    new_db_name = 'optimed_dev'

    print_header("🆕 Create New OptiMed Development Database")

    print(f"Target: {db_host}:{db_port}")
    print(f"New database name: {new_db_name}")
    print()

    # Try each strategy
    connected = False
    conn = None
    strategy_used = None

    for strategy in strategies:
        print(f"Trying: {strategy['name']}...")

        try:
            conn = psycopg2.connect(
                host=db_host,
                port=db_port,
                user=strategy['user'],
                password=strategy['password'],
                database='postgres',
                connect_timeout=3
            )
            conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            connected = True
            strategy_used = strategy
            print("✅ Connected successfully!")
            print()
            break

        except psycopg2.OperationalError as e:
            print(f"   ❌ Failed: {str(e)[:100]}")
            continue
        except Exception as e:
            print(f"   ❌ Failed: {e}")
            continue

    if not connected:
        print()
        print("❌ Could not connect with any known credentials.")
        print()
        print_postgres_reset_instructions()
        sys.exit(1)

    cursor = conn.cursor()

    try:
        # Check if database already exists
        cursor.execute(f"""
            SELECT 1 FROM pg_database WHERE datname = '{new_db_name}';
        """)

        if cursor.fetchone():
            print(f"⚠️  Database '{new_db_name}' already exists.")
            response = input("Drop and recreate it? (yes/no): ")
            if response.lower() == 'yes':
                # Terminate connections
                cursor.execute(f"""
                    SELECT pg_terminate_backend(pg_stat_activity.pid)
                    FROM pg_stat_activity
                    WHERE pg_stat_activity.datname = '{new_db_name}'
                      AND pid <> pg_backend_pid();
                """)
                cursor.execute(f"DROP DATABASE {new_db_name};")
                print("✅ Dropped existing database")
            else:
                print("❌ Aborted.")
                sys.exit(0)

        # Create new database
        print(f"🆕 Creating database '{new_db_name}'...")
        cursor.execute(f"CREATE DATABASE {new_db_name};")
        print("✅ Database created successfully!")
        print()

        # Grant privileges to optimed_user
        user = os.getenv('POSTGRES_USER', 'optimed_user')
        print(f"🔑 Granting privileges to '{user}'...")

        try:
            cursor.execute(f"GRANT ALL PRIVILEGES ON DATABASE {new_db_name} TO {user};")
            print(f"✅ Privileges granted to '{user}'")
        except Exception as e:
            print(f"⚠️  Could not grant privileges: {e}")
            print("   You may need to grant privileges manually")

        cursor.close()
        conn.close()

        # Connect to new database and enable extensions
        print()
        print("🔧 Enabling extensions...")

        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            user=strategy_used['user'],
            password=strategy_used['password'],
            database=new_db_name
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()

        extensions = [
            ('vector', 'pgvector for embeddings'),
            ('pgcrypto', 'cryptographic functions')
        ]

        for ext_name, ext_desc in extensions:
            try:
                cursor.execute(f"CREATE EXTENSION IF NOT EXISTS {ext_name};")
                print(f"  ✅ {ext_name} - {ext_desc}")
            except Exception as e:
                print(f"  ⚠️  {ext_name} - {str(e)[:80]}")

        cursor.close()
        conn.close()

        # Update .env file
        print()
        print("📝 Updating .env file...")

        env_path = os.path.join(os.path.dirname(__file__), '..', '.env')

        with open(env_path, 'r') as f:
            lines = f.readlines()

        # Update relevant lines
        updated = False
        for i, line in enumerate(lines):
            if line.startswith('POSTGRES_DB='):
                lines[i] = f'POSTGRES_DB={new_db_name}\n'
                updated = True
            elif line.startswith('PGVECTOR_DSN='):
                new_dsn = f'postgresql://{user}:{os.getenv("POSTGRES_PASSWORD", "test_user")}@{db_host}:{db_port}/{new_db_name}'
                lines[i] = f'PGVECTOR_DSN={new_dsn} #postgresql://optimed_admin:clara_passkey@optimed-db-sweden.postgres.database.azure.com:5432/optimed?sslmode=require\n'
                updated = True

        if updated:
            with open(env_path, 'w') as f:
                f.writelines(lines)
            print("✅ .env file updated")
            print(f"   POSTGRES_DB={new_db_name}")
            print(f"   PGVECTOR_DSN=postgresql://{user}:***@{db_host}:{db_port}/{new_db_name}")

        print()
        print_header("✅ Setup Complete!")

        print("Next steps:")
        print(f"  1. Verify .env points to '{new_db_name}'")
        print("  2. Run migrations:")
        print("     python scripts/run_migrations.py")
        print()

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    create_new_database()
