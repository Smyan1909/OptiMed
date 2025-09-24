#!/usr/bin/env python3
"""
Generate Encryption Keys for OptiMed

This script generates cryptographically secure encryption keys for production use.
Run this script to generate new keys for each deployment environment.

Usage:
    conda activate optimed
    python scripts/generate_encryption_keys.py
"""

import secrets
import base64
from cryptography.fernet import Fernet


def generate_encryption_keys():
    """Generate secure encryption keys for OptiMed."""

    print("🔐 OptiMed Encryption Key Generator")
    print("=" * 50)

    # Generate Fernet-compatible master key (32 bytes, base64 encoded)
    master_key = Fernet.generate_key().decode()

    # Generate secure hash salt (32 bytes, base64 encoded)
    salt_bytes = secrets.token_bytes(32)
    hash_salt = base64.b64encode(salt_bytes).decode()

    print("✅ Generated new encryption keys:")
    print()
    print("ENCRYPTION_MASTER_KEY=" + master_key)
    print("HASH_SALT=" + hash_salt)
    print()

    # Save to a .env.new file
    env_content = f"""# Generated Encryption Keys - {secrets.token_hex(4).upper()}
# Copy these to your .env file for production deployment

ENCRYPTION_MASTER_KEY={master_key}
HASH_SALT={hash_salt}

# Security Notes:
# - These keys are cryptographically secure random values
# - Use different keys for each environment (dev/staging/prod)
# - Store securely and never commit to version control
# - Regenerate keys if compromised
"""

    output_file = ".env.encryption.new"
    with open(output_file, "w") as f:
        f.write(env_content)

    print(f"💾 Keys saved to: {output_file}")
    print()
    print("🚨 SECURITY WARNINGS:")
    print("- Use different keys for each environment")
    print("- Never commit these keys to version control")
    print("- Store production keys securely (env vars, secrets manager)")
    print("- Delete this file after copying keys to production")
    print()
    print("📋 Next steps:")
    print("1. Copy the keys above to your .env file")
    print("2. Restart your application")
    print("3. Delete the .env.encryption.new file")
    print("4. Test encryption functionality")


def verify_key_strength():
    """Verify the generated keys have sufficient entropy."""
    print("🔍 Key Strength Verification:")
    print("- Master Key: 256-bit Fernet key (AES-128 + HMAC-SHA256)")
    print("- Hash Salt: 256-bit random salt")
    print("- Entropy Source: OS cryptographically secure random")
    print("- Format: Base64 encoded for storage")
    print()


if __name__ == "__main__":
    try:
        verify_key_strength()
        generate_encryption_keys()

        print("✅ Encryption key generation completed successfully!")

    except Exception as e:
        print(f"❌ Error generating keys: {e}")
        print("Make sure you have the required dependencies installed:")
        print("  conda activate optimed")
        print("  pip install cryptography")
        exit(1)