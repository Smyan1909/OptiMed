"""
Database-Level Encryption Service

Provides encryption/decryption using PostgreSQL pgcrypto extension.
Integrates with application-level encryption for defense-in-depth.

Uses AES-256 encryption via pgp_sym_encrypt/decrypt functions.
"""

import os
import hashlib
import asyncpg
from typing import Optional
from optimed.core.logging_utils import get_logger, log_error

logger = get_logger(__name__)


class DatabaseEncryption:
    """
    Database encryption service using PostgreSQL pgcrypto.

    Provides:
    - AES-256 encryption for sensitive fields (tokens, credentials)
    - SHA-256 hashing for pseudonymization (emails, names, phones)
    - Automatic key management via environment variables
    """

    def __init__(self, encryption_key: Optional[str] = None):
        """
        Initialize database encryption service.

        Args:
            encryption_key: Master encryption key (or reads from ENCRYPTION_MASTER_KEY env)
        """
        self.encryption_key = encryption_key or os.getenv("ENCRYPTION_MASTER_KEY")

        if not self.encryption_key:
            logger.warning("ENCRYPTION_MASTER_KEY not set - encryption will fail in production!")
            self.encryption_key = "dev-key-change-me-in-production"

    @staticmethod
    def hash_value(value: Optional[str]) -> Optional[str]:
        """
        Create SHA-256 hash of a value (client-side, no database call).

        Args:
            value: Value to hash

        Returns:
            64-character hex string or None if value is None
        """
        if not value:
            return None
        return hashlib.sha256(value.encode('utf-8')).hexdigest()

    async def encrypt_field(
        self,
        conn: asyncpg.Connection,
        plaintext: Optional[str]
    ) -> Optional[bytes]:
        """
        Encrypt a field using database encrypt_text() function.

        Args:
            conn: Database connection
            plaintext: Text to encrypt

        Returns:
            Encrypted bytes or None if plaintext is None
        """
        if not plaintext:
            return None

        try:
            encrypted = await conn.fetchval(
                "SELECT encrypt_text($1, $2)",
                plaintext,
                self.encryption_key
            )
            return encrypted
        except Exception as e:
            log_error(logger, "Error encrypting field", e)
            raise

    async def decrypt_field(
        self,
        conn: asyncpg.Connection,
        ciphertext: Optional[bytes]
    ) -> Optional[str]:
        """
        Decrypt a field using database decrypt_text() function.

        Args:
            conn: Database connection
            ciphertext: Encrypted bytes

        Returns:
            Decrypted plaintext or None if ciphertext is None
        """
        if not ciphertext:
            return None

        try:
            decrypted = await conn.fetchval(
                "SELECT decrypt_text($1, $2)",
                ciphertext,
                self.encryption_key
            )
            return decrypted
        except Exception as e:
            log_error(logger, "Error decrypting field", e)
            raise

    async def hash_field(
        self,
        conn: asyncpg.Connection,
        plaintext: Optional[str]
    ) -> Optional[str]:
        """
        Hash a field using database hash_text() function.

        Args:
            conn: Database connection
            plaintext: Text to hash

        Returns:
            64-character hex string or None if plaintext is None
        """
        if not plaintext:
            return None

        try:
            hashed = await conn.fetchval(
                "SELECT hash_text($1)",
                plaintext
            )
            return hashed
        except Exception as e:
            log_error(logger, "Error hashing field", e)
            raise

    @staticmethod
    def should_encrypt(value: Optional[str]) -> bool:
        """
        Check if a value should be encrypted (not already encrypted or placeholder).

        Args:
            value: Value to check

        Returns:
            True if value needs encryption, False otherwise
        """
        if not value:
            return False

        # Don't re-encrypt if already marked as encrypted
        if value in ['[ENCRYPTED]', '[REDACTED]', '[HASHED]']:
            return False

        return True

    async def encrypt_connection_tokens(
        self,
        conn: asyncpg.Connection,
        access_token: Optional[str],
        refresh_token: Optional[str],
        credentials: Optional[str]
    ) -> tuple[Optional[bytes], Optional[bytes], Optional[bytes]]:
        """
        Encrypt all EHR connection tokens in one call.

        Args:
            conn: Database connection
            access_token: Access token to encrypt
            refresh_token: Refresh token to encrypt
            credentials: Credentials JSON to encrypt

        Returns:
            Tuple of (access_token_encrypted, refresh_token_encrypted, credentials_encrypted)
        """
        access_encrypted = await self.encrypt_field(conn, access_token) if self.should_encrypt(access_token) else None
        refresh_encrypted = await self.encrypt_field(conn, refresh_token) if self.should_encrypt(refresh_token) else None
        creds_encrypted = await self.encrypt_field(conn, credentials) if self.should_encrypt(credentials) else None

        return access_encrypted, refresh_encrypted, creds_encrypted

    async def decrypt_connection_tokens(
        self,
        conn: asyncpg.Connection,
        access_token_encrypted: Optional[bytes],
        refresh_token_encrypted: Optional[bytes],
        credentials_encrypted: Optional[bytes]
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Decrypt all EHR connection tokens in one call.

        Args:
            conn: Database connection
            access_token_encrypted: Encrypted access token
            refresh_token_encrypted: Encrypted refresh token
            credentials_encrypted: Encrypted credentials

        Returns:
            Tuple of (access_token, refresh_token, credentials)
        """
        access = await self.decrypt_field(conn, access_token_encrypted)
        refresh = await self.decrypt_field(conn, refresh_token_encrypted)
        creds = await self.decrypt_field(conn, credentials_encrypted)

        return access, refresh, creds

    def hash_user_pii(
        self,
        email: Optional[str],
        phone: Optional[str],
        first_name: Optional[str],
        last_name: Optional[str]
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Hash user PII (client-side, no database call for performance).

        Args:
            email: Email to hash
            phone: Phone to hash
            first_name: First name
            last_name: Last name

        Returns:
            Tuple of (email_hash, phone_hash, name_hash)
        """
        email_hash = self.hash_value(email)
        phone_hash = self.hash_value(phone)

        # Hash full name
        name_hash = None
        if first_name or last_name:
            full_name = f"{first_name or ''} {last_name or ''}".strip()
            name_hash = self.hash_value(full_name) if full_name else None

        return email_hash, phone_hash, name_hash

    async def verify_encryption_setup(self, conn: asyncpg.Connection) -> bool:
        """
        Verify that encryption functions are available and working.

        Args:
            conn: Database connection

        Returns:
            True if encryption is working, False otherwise
        """
        try:
            # Test encryption
            test_text = "test-encryption-verification"
            encrypted = await conn.fetchval(
                "SELECT encrypt_text($1, $2)",
                test_text,
                self.encryption_key
            )

            if not encrypted:
                logger.error("Encryption test failed - encrypt_text returned NULL")
                return False

            # Test decryption
            decrypted = await conn.fetchval(
                "SELECT decrypt_text($1, $2)",
                encrypted,
                self.encryption_key
            )

            if decrypted != test_text:
                logger.error(f"Decryption test failed - expected '{test_text}', got '{decrypted}'")
                return False

            # Test hashing
            test_hash = await conn.fetchval(
                "SELECT hash_text($1)",
                "test@example.com"
            )

            if not test_hash or len(test_hash) != 64:  # SHA-256 = 64 hex chars
                logger.error(f"Hashing test failed - hash length {len(test_hash) if test_hash else 0}")
                return False

            logger.info("Database encryption verification successful ✓")
            return True

        except Exception as e:
            log_error(logger, "Database encryption verification failed", e)
            return False


# Global instance
_db_encryption: Optional[DatabaseEncryption] = None


def get_database_encryption(encryption_key: Optional[str] = None) -> DatabaseEncryption:
    """
    Get global DatabaseEncryption instance.

    Args:
        encryption_key: Optional encryption key (uses env var if not provided)

    Returns:
        DatabaseEncryption instance
    """
    global _db_encryption
    if _db_encryption is None:
        _db_encryption = DatabaseEncryption(encryption_key)
    return _db_encryption
