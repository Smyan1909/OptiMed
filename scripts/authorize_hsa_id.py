#!/usr/bin/env python3
"""
Simple script to authorize HSA IDs for SITHS authentication.
Creates minimal user records - details will be filled in from SITHS certificate on first login.
"""

import asyncio
import asyncpg
import sys
import os
import uuid
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


async def authorize_hsa_id(hsa_id: str, role: str = "doctor"):
    """
    Pre-authorize an HSA ID by creating a minimal user record.
    User details will be filled in from SITHS certificate on first login.

    Args:
        hsa_id: The HSA ID to authorize (e.g., SE123456789012)
        role: User role (default: doctor)
    """
    dsn = os.getenv("PGVECTOR_DSN")
    if not dsn:
        print("ERROR: PGVECTOR_DSN environment variable not set")
        sys.exit(1)

    conn = await asyncpg.connect(dsn)

    try:
        # Check if HSA ID already exists
        existing = await conn.fetchrow(
            "SELECT user_id, username, email FROM users WHERE hsa_id = $1",
            hsa_id
        )

        if existing:
            print(f"❌ HSA ID '{hsa_id}' is already authorized!")
            print(f"   User ID: {existing['user_id']}")
            print(f"   Username: {existing['username']}")
            print(f"   Email: {existing['email']}")
            print("\nUse update_hsa_id.py to modify existing user.")
            return False

        # Generate unique user ID
        user_id = f"siths_{uuid.uuid4().hex[:12]}"

        # Create minimal user record
        # Username and email are placeholders - will be updated on first SITHS login
        await conn.execute("""
            INSERT INTO users (
                user_id,
                username,
                email,
                first_name,
                last_name,
                role,
                status,
                hsa_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
            user_id,
            f"hsa_{hsa_id}",  # Placeholder username
            f"{hsa_id}@pending.local",  # Placeholder email
            "Pending",  # Will be filled from certificate
            "SITHS Login",  # Will be filled from certificate
            role,
            "active",
            hsa_id
        )

        print("✅ HSA ID authorized successfully!")
        print(f"\n📋 User Details:")
        print(f"   HSA ID: {hsa_id}")
        print(f"   User ID: {user_id}")
        print(f"   Role: {role}")
        print(f"   Status: active")
        print(f"\n📝 Note: Name and email will be automatically filled in from")
        print(f"   SITHS certificate when the user logs in for the first time.")

        return True

    except Exception as e:
        print(f"❌ Error authorizing HSA ID: {str(e)}")
        return False

    finally:
        await conn.close()


async def list_authorized_hsa_ids():
    """List all authorized HSA IDs."""
    dsn = os.getenv("PGVECTOR_DSN")
    if not dsn:
        print("ERROR: PGVECTOR_DSN environment variable not set")
        sys.exit(1)

    conn = await asyncpg.connect(dsn)

    try:
        users = await conn.fetch("""
            SELECT user_id, username, email, first_name, last_name, hsa_id, role, status
            FROM users
            WHERE hsa_id IS NOT NULL
            ORDER BY created_at DESC
        """)

        if not users:
            print("📋 No authorized HSA IDs found.")
            return

        print(f"\n📋 Authorized HSA IDs ({len(users)}):")
        print("=" * 80)

        for user in users:
            # Check if it's a placeholder (not yet logged in)
            is_placeholder = user['email'].endswith('@pending.local')

            print(f"\nHSA ID: {user['hsa_id']}")
            print(f"User ID: {user['user_id']}")
            print(f"Name: {user['first_name'] or 'N/A'} {user['last_name'] or 'N/A'}")
            print(f"Email: {user['email']}")
            print(f"Role: {user['role']}")
            print(f"Status: {user['status']}")

            if is_placeholder:
                print("⏳ Status: Authorized but not yet logged in")
            else:
                print("✅ Status: Has logged in (details from SITHS certificate)")

            print("-" * 80)

    finally:
        await conn.close()


async def revoke_hsa_id(hsa_id: str):
    """
    Revoke access for an HSA ID by setting status to inactive.
    Does not delete the user, just blocks login.
    """
    dsn = os.getenv("PGVECTOR_DSN")
    if not dsn:
        print("ERROR: PGVECTOR_DSN environment variable not set")
        sys.exit(1)

    conn = await asyncpg.connect(dsn)

    try:
        # Update user status to inactive
        result = await conn.execute(
            "UPDATE users SET status = 'inactive' WHERE hsa_id = $1 AND status = 'active'",
            hsa_id
        )

        if result == "UPDATE 0":
            print(f"❌ HSA ID '{hsa_id}' not found or already inactive")
            return False

        print(f"✅ Access revoked for HSA ID: {hsa_id}")
        print(f"   User status set to: inactive")
        print(f"\n   Note: User record still exists but cannot login.")
        print(f"   Use 'reactivate' command to restore access.")

        return True

    except Exception as e:
        print(f"❌ Error revoking HSA ID: {str(e)}")
        return False

    finally:
        await conn.close()


async def reactivate_hsa_id(hsa_id: str):
    """Reactivate a previously revoked HSA ID."""
    dsn = os.getenv("PGVECTOR_DSN")
    if not dsn:
        print("ERROR: PGVECTOR_DSN environment variable not set")
        sys.exit(1)

    conn = await asyncpg.connect(dsn)

    try:
        result = await conn.execute(
            "UPDATE users SET status = 'active' WHERE hsa_id = $1 AND status = 'inactive'",
            hsa_id
        )

        if result == "UPDATE 0":
            print(f"❌ HSA ID '{hsa_id}' not found or already active")
            return False

        print(f"✅ Access reactivated for HSA ID: {hsa_id}")
        print(f"   User can now login again.")

        return True

    except Exception as e:
        print(f"❌ Error reactivating HSA ID: {str(e)}")
        return False

    finally:
        await conn.close()


def print_usage():
    """Print usage instructions."""
    print("""
╔════════════════════════════════════════════════════════════════════════╗
║              SITHS HSA ID Authorization Manager                       ║
╚════════════════════════════════════════════════════════════════════════╝

USAGE:
    python scripts/authorize_hsa_id.py <command> [options]

COMMANDS:

    authorize <HSA_ID> [role]
        Pre-authorize an HSA ID for SITHS login
        User details will be filled in from certificate on first login

        Example:
            python scripts/authorize_hsa_id.py authorize SE123456789012
            python scripts/authorize_hsa_id.py authorize SE123456789012 doctor

    list
        List all authorized HSA IDs

        Example:
            python scripts/authorize_hsa_id.py list

    revoke <HSA_ID>
        Revoke access for an HSA ID (sets status to inactive)

        Example:
            python scripts/authorize_hsa_id.py revoke SE123456789012

    reactivate <HSA_ID>
        Reactivate a previously revoked HSA ID

        Example:
            python scripts/authorize_hsa_id.py reactivate SE123456789012

ROLES:
    - doctor (default)
    - nurse
    - admin

WORKFLOW:
    1. Admin runs: authorize_hsa_id.py authorize SE123456789012
    2. User tries to login with SITHS card
    3. System checks if HSA ID is pre-authorized (whitelist check)
    4. If authorized, user is logged in
    5. Name, email, etc. are automatically filled from SITHS certificate

ENVIRONMENT:
    Requires PGVECTOR_DSN environment variable to be set.

EXAMPLES:

    # Authorize a doctor
    python scripts/authorize_hsa_id.py authorize SE123456789012 doctor

    # List all authorized HSA IDs
    python scripts/authorize_hsa_id.py list

    # Revoke access
    python scripts/authorize_hsa_id.py revoke SE123456789012

    # Restore access
    python scripts/authorize_hsa_id.py reactivate SE123456789012

""")


async def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "authorize":
        if len(sys.argv) < 3:
            print("❌ Error: HSA ID required")
            print("\nUsage: python scripts/authorize_hsa_id.py authorize <HSA_ID> [role]")
            sys.exit(1)

        hsa_id = sys.argv[2]
        role = sys.argv[3] if len(sys.argv) > 3 else "doctor"

        if role not in ["doctor", "nurse", "admin"]:
            print(f"❌ Error: Invalid role '{role}'")
            print("   Valid roles: doctor, nurse, admin")
            sys.exit(1)

        await authorize_hsa_id(hsa_id, role)

    elif command == "list":
        await list_authorized_hsa_ids()

    elif command == "revoke":
        if len(sys.argv) < 3:
            print("❌ Error: HSA ID required")
            print("\nUsage: python scripts/authorize_hsa_id.py revoke <HSA_ID>")
            sys.exit(1)

        hsa_id = sys.argv[2]
        await revoke_hsa_id(hsa_id)

    elif command == "reactivate":
        if len(sys.argv) < 3:
            print("❌ Error: HSA ID required")
            print("\nUsage: python scripts/authorize_hsa_id.py reactivate <HSA_ID>")
            sys.exit(1)

        hsa_id = sys.argv[2]
        await reactivate_hsa_id(hsa_id)

    elif command in ["help", "-h", "--help"]:
        print_usage()

    else:
        print(f"❌ Error: Unknown command '{command}'")
        print("\nRun 'python scripts/authorize_hsa_id.py help' for usage information")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
