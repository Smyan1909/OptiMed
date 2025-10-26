#!/usr/bin/env python3
"""
HSA ID Management Script

This script allows administrators to manage HSA IDs for SITHS authentication.
HSA IDs act as a whitelist - only users with pre-approved HSA IDs can login via SITHS.

Usage:
    python scripts/manage_hsa_ids.py add --username doctor1 --hsa-id SE123456789012
    python scripts/manage_hsa_ids.py create --hsa-id SE9876543210 --email new.doctor@hospital.se
    python scripts/manage_hsa_ids.py list
    python scripts/manage_hsa_ids.py remove --username doctor1
    python scripts/manage_hsa_ids.py import --csv hsa_ids.csv

CSV Format for import:
    username,hsa_id,email,first_name,last_name,role
    doctor1,SE123456789012,doctor1@hospital.se,John,Doe,doctor
"""

import asyncio
import argparse
import csv
import os
import sys
import uuid

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from optimed.adapters.user_repository.pg_user_repository import PGUserRepository
from optimed.core.domain import User, UserRole, UserStatus
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def get_dsn() -> str:
    """Get database DSN from environment."""
    dsn = os.getenv('PGVECTOR_DSN')
    if not dsn:
        raise ValueError("PGVECTOR_DSN environment variable not set")
    return dsn


async def add_hsa_id(args):
    """Add HSA ID to an existing user."""
    dsn = get_dsn()
    repo = PGUserRepository(dsn)

    try:
        # Find user by username or email
        if args.username:
            user = await repo.get_user_by_username(args.username)
            identifier = f"username '{args.username}'"
        elif args.email:
            user = await repo.get_user_by_email(args.email)
            identifier = f"email '{args.email}'"
        else:
            print("Error: Must provide either --username or --email")
            return

        if not user:
            print(f"Error: User with {identifier} not found")
            return

        # Check if HSA ID is already in use
        existing = await repo.get_user_by_hsa_id(args.hsa_id)
        if existing and existing.user_id != user.user_id:
            print(f"Error: HSA ID '{args.hsa_id}' is already assigned to user '{existing.username}'")
            return

        # Update user with HSA ID
        updated_user = user.model_copy(update={'hsa_id': args.hsa_id})
        await repo.update_user(updated_user)

        print(f"✓ Successfully added HSA ID '{args.hsa_id}' to user '{user.username}'")
        print(f"  User: {user.full_name} ({user.email})")
        print(f"  Role: {user.role.value}")

    finally:
        await repo.close()


async def create_user_with_hsa_id(args):
    """Create a new user with HSA ID pre-populated."""
    dsn = get_dsn()
    repo = PGUserRepository(dsn)

    try:
        # Check if HSA ID already exists
        existing = await repo.get_user_by_hsa_id(args.hsa_id)
        if existing:
            print(f"Error: HSA ID '{args.hsa_id}' is already assigned to user '{existing.username}'")
            return

        # Check if username/email already exists
        if await repo.get_user_by_email(args.email):
            print(f"Error: User with email '{args.email}' already exists")
            return

        username = args.username or args.email.split('@')[0]
        if await repo.get_user_by_username(username):
            print(f"Error: User with username '{username}' already exists")
            return

        # Create new user
        user_role = UserRole(args.role) if args.role else UserRole.DOCTOR
        user = User(
            user_id=str(uuid.uuid4()),
            username=username,
            email=args.email,
            first_name=args.first_name or "",
            last_name=args.last_name or "",
            role=user_role,
            status=UserStatus.ACTIVE,
            hsa_id=args.hsa_id,
            department=args.department,
            license_number=args.license_number
        )

        await repo.create_user(user)

        print(f"✓ Successfully created user with HSA ID '{args.hsa_id}'")
        print(f"  Username: {user.username}")
        print(f"  Email: {user.email}")
        print(f"  Name: {user.full_name}")
        print(f"  Role: {user.role.value}")

    finally:
        await repo.close()


async def list_hsa_ids(args):
    """List all users with their HSA IDs."""
    dsn = get_dsn()
    repo = PGUserRepository(dsn)

    try:
        pool = await repo._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT user_id, username, email, first_name, last_name, hsa_id, role, status
                FROM users
                ORDER BY username
            """)

        if not rows:
            print("No users found")
            return

        print("\n" + "=" * 100)
        print(f"{'Username':<20} {'HSA ID':<20} {'Name':<25} {'Email':<30}")
        print("=" * 100)

        for row in rows:
            hsa_id = row['hsa_id'] or '(not set)'
            name = f"{row['first_name']} {row['last_name']}".strip() or '(no name)'
            print(f"{row['username']:<20} {hsa_id:<20} {name:<25} {row['email']:<30}")

        print("=" * 100)
        print(f"\nTotal users: {len(rows)}")
        print(f"Users with HSA ID: {sum(1 for r in rows if r['hsa_id'])}")

    finally:
        await repo.close()


async def remove_hsa_id(args):
    """Remove HSA ID from a user (revoke SITHS access)."""
    dsn = get_dsn()
    repo = PGUserRepository(dsn)

    try:
        # Find user
        if args.username:
            user = await repo.get_user_by_username(args.username)
            identifier = f"username '{args.username}'"
        elif args.email:
            user = await repo.get_user_by_email(args.email)
            identifier = f"email '{args.email}'"
        else:
            print("Error: Must provide either --username or --email")
            return

        if not user:
            print(f"Error: User with {identifier} not found")
            return

        if not user.hsa_id:
            print(f"Warning: User '{user.username}' does not have an HSA ID")
            return

        # Remove HSA ID
        updated_user = user.model_copy(update={'hsa_id': None})
        await repo.update_user(updated_user)

        print(f"✓ Successfully removed HSA ID from user '{user.username}'")
        print("  User will no longer be able to login via SITHS")

    finally:
        await repo.close()


async def import_from_csv(args):
    """Import HSA IDs from CSV file."""
    dsn = get_dsn()
    repo = PGUserRepository(dsn)

    try:
        if not os.path.exists(args.csv):
            print(f"Error: File '{args.csv}' not found")
            return

        with open(args.csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            print("Error: CSV file is empty")
            return

        print(f"Found {len(rows)} entries in CSV file")
        print("Processing...")

        created = 0
        updated = 0
        errors = 0

        for i, row in enumerate(rows, 1):
            try:
                username = row.get('username', '').strip()
                hsa_id = row.get('hsa_id', '').strip()
                email = row.get('email', '').strip()

                if not hsa_id:
                    print(f"  Row {i}: Skipping - no HSA ID")
                    continue

                # Check if user exists by username or email
                user = None
                if username:
                    user = await repo.get_user_by_username(username)
                if not user and email:
                    user = await repo.get_user_by_email(email)

                if user:
                    # Update existing user
                    updated_user = user.model_copy(update={'hsa_id': hsa_id})
                    await repo.update_user(updated_user)
                    print(f"  Row {i}: Updated user '{user.username}' with HSA ID '{hsa_id}'")
                    updated += 1
                else:
                    # Create new user
                    if not email:
                        print(f"  Row {i}: Error - email required for new user")
                        errors += 1
                        continue

                    user_role = UserRole(row.get('role', 'doctor'))
                    new_user = User(
                        user_id=str(uuid.uuid4()),
                        username=username or email.split('@')[0],
                        email=email,
                        first_name=row.get('first_name', ''),
                        last_name=row.get('last_name', ''),
                        role=user_role,
                        status=UserStatus.ACTIVE,
                        hsa_id=hsa_id,
                        department=row.get('department'),
                        license_number=row.get('license_number')
                    )
                    await repo.create_user(new_user)
                    print(f"  Row {i}: Created user '{new_user.username}' with HSA ID '{hsa_id}'")
                    created += 1

            except Exception as e:
                print(f"  Row {i}: Error - {str(e)}")
                errors += 1

        print("\n" + "=" * 60)
        print("Import complete:")
        print(f"  Created: {created}")
        print(f"  Updated: {updated}")
        print(f"  Errors: {errors}")
        print("=" * 60)

    finally:
        await repo.close()


def main():
    parser = argparse.ArgumentParser(
        description='Manage HSA IDs for SITHS authentication',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # Add command
    add_parser = subparsers.add_parser('add', help='Add HSA ID to existing user')
    add_parser.add_argument('--username', help='Username of the user')
    add_parser.add_argument('--email', help='Email of the user')
    add_parser.add_argument('--hsa-id', required=True, help='HSA ID to add (e.g., SE123456789012)')

    # Create command
    create_parser = subparsers.add_parser('create', help='Create new user with HSA ID')
    create_parser.add_argument('--hsa-id', required=True, help='HSA ID for the new user')
    create_parser.add_argument('--email', required=True, help='Email address')
    create_parser.add_argument('--username', help='Username (defaults to email prefix)')
    create_parser.add_argument('--first-name', help='First name')
    create_parser.add_argument('--last-name', help='Last name')
    create_parser.add_argument('--role', choices=['doctor', 'admin', 'nurse'], default='doctor', help='User role')
    create_parser.add_argument('--department', help='Department')
    create_parser.add_argument('--license-number', help='Medical license number')

    # List command
    subparsers.add_parser('list', help='List all users with HSA IDs')

    # Remove command
    remove_parser = subparsers.add_parser('remove', help='Remove HSA ID from user')
    remove_parser.add_argument('--username', help='Username of the user')
    remove_parser.add_argument('--email', help='Email of the user')

    # Import command
    import_parser = subparsers.add_parser('import', help='Import HSA IDs from CSV file')
    import_parser.add_argument('--csv', required=True, help='Path to CSV file')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Run the appropriate command
    if args.command == 'add':
        asyncio.run(add_hsa_id(args))
    elif args.command == 'create':
        asyncio.run(create_user_with_hsa_id(args))
    elif args.command == 'list':
        asyncio.run(list_hsa_ids(args))
    elif args.command == 'remove':
        asyncio.run(remove_hsa_id(args))
    elif args.command == 'import':
        asyncio.run(import_from_csv(args))


if __name__ == '__main__':
    main()
