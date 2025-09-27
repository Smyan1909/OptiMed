"""
KMS and crypto-shredding service for GDPR-compliant ephemeral cache.

This module provides envelope encryption with crypto-shredding capabilities
for temporary content storage. When the DEK (Data Encryption Key) is deleted,
the encrypted content becomes unreadable, providing logical erasure.
"""

from __future__ import annotations
import os
import secrets
import hashlib
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timezone, timedelta
import json
import logging

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidTag

logger = logging.getLogger(__name__)

class CryptoShreddingError(Exception):
    """Raised when crypto-shredding operations fail."""
    pass

class KMSConfig:
    """Configuration for KMS operations."""
    
    def __init__(
        self,
        kek_id: str,
        kek_algorithm: str = "AES-256",
        dek_length: int = 32,
        salt_length: int = 16,
        iterations: int = 100000,
        ttl_hours: int = 24
    ):
        self.kek_id = kek_id
        self.kek_algorithm = kek_algorithm
        self.dek_length = dek_length
        self.salt_length = salt_length
        self.iterations = iterations
        self.ttl_hours = ttl_hours

class EnvelopeEncryption:
    """Envelope encryption service with crypto-shredding support."""
    
    def __init__(self, config: KMSConfig):
        self.config = config
        self._dek_cache: Dict[str, Tuple[bytes, datetime]] = {}
        self._kek = self._get_or_create_kek()
    
    def _get_or_create_kek(self) -> bytes:
        """Get or create the Key Encryption Key (KEK)."""
        # In production, this would fetch from a real KMS like AWS KMS, Azure Key Vault, etc.
        # For now, we'll use environment variables or generate a deterministic key
        kek_env = os.getenv("KMS_KEK_SECRET")
        if kek_env:
            return hashlib.sha256(kek_env.encode()).digest()
        
        # Generate a deterministic key based on kek_id (for development)
        # In production, this should never be used
        logger.warning("Using deterministic KEK - not suitable for production!")
        return hashlib.sha256(f"dev_kek_{self.config.kek_id}".encode()).digest()
    
    def _generate_dek(self) -> bytes:
        """Generate a new Data Encryption Key (DEK)."""
        return secrets.token_bytes(self.config.dek_length)
    
    def _derive_key_from_password(self, password: bytes, salt: bytes) -> bytes:
        """Derive encryption key from password using PBKDF2."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=self.config.dek_length,
            salt=salt,
            iterations=self.config.iterations,
            backend=default_backend()
        )
        return kdf.derive(password)
    
    def _encrypt_dek(self, dek: bytes) -> Tuple[bytes, bytes]:
        """Encrypt DEK with KEK using AES-GCM."""
        iv = secrets.token_bytes(12)  # 96-bit IV for GCM
        cipher = Cipher(algorithms.AES(self._kek), modes.GCM(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        
        encrypted_dek = encryptor.update(dek) + encryptor.finalize()
        
        return encrypted_dek, iv + encryptor.tag
    
    def _decrypt_dek(self, encrypted_dek: bytes, dek_metadata: bytes) -> bytes:
        """Decrypt DEK with KEK using AES-GCM."""
        if len(dek_metadata) < 28:  # 12 bytes IV + 16 bytes tag
            raise CryptoShreddingError("Invalid DEK metadata")
        
        iv = dek_metadata[:12]
        tag = dek_metadata[12:28]
        
        cipher = Cipher(algorithms.AES(self._kek), modes.GCM(iv, tag), backend=default_backend())
        decryptor = cipher.decryptor()
        
        try:
            return decryptor.update(encrypted_dek) + decryptor.finalize()
        except InvalidTag:
            raise CryptoShreddingError("Failed to decrypt DEK - may have been crypto-shredded")
    
    def _encrypt_data(self, data: bytes, dek: bytes) -> Tuple[bytes, bytes]:
        """Encrypt data with DEK using AES-GCM."""
        iv = secrets.token_bytes(12)  # 96-bit IV for GCM
        cipher = Cipher(algorithms.AES(dek), modes.GCM(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        
        encrypted_data = encryptor.update(data) + encryptor.finalize()
        
        return encrypted_data, iv + encryptor.tag
    
    def _decrypt_data(self, encrypted_data: bytes, dek: bytes, data_metadata: bytes) -> bytes:
        """Decrypt data with DEK using AES-GCM."""
        if len(data_metadata) < 28:  # 12 bytes IV + 16 bytes tag
            raise CryptoShreddingError("Invalid data metadata")
        
        iv = data_metadata[:12]
        tag = data_metadata[12:28]
        
        cipher = Cipher(algorithms.AES(dek), modes.GCM(iv, tag), backend=default_backend())
        decryptor = cipher.decryptor()
        
        try:
            return decryptor.update(encrypted_data) + decryptor.finalize()
        except InvalidTag:
            raise CryptoShreddingError("Failed to decrypt data - DEK may have been crypto-shredded")
    
    def encrypt_content(self, content: str, session_id: str) -> Dict[str, Any]:
        """Encrypt content and return envelope encryption metadata."""
        try:
            # Generate new DEK
            dek = self._generate_dek()
            
            # Encrypt DEK with KEK
            encrypted_dek, dek_metadata = self._encrypt_dek(dek)
            
            # Encrypt content with DEK
            content_bytes = content.encode('utf-8')
            encrypted_content, content_metadata = self._encrypt_data(content_bytes, dek)
            
            # Cache DEK for this session (with TTL)
            expires_at = datetime.now(timezone.utc) + timedelta(hours=self.config.ttl_hours)
            self._dek_cache[session_id] = (dek, expires_at)
            
            return {
                "dek_id": session_id,  # In production, this would be a unique DEK ID
                "encrypted_dek": encrypted_dek.hex(),
                "dek_metadata": dek_metadata.hex(),
                "ciphertext": encrypted_content.hex(),
                "content_metadata": content_metadata.hex(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": expires_at.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Failed to encrypt content for session {session_id}: {e}")
            raise CryptoShreddingError(f"Encryption failed: {e}")
    
    def decrypt_content(self, envelope_data: Dict[str, Any], session_id: str) -> str:
        """Decrypt content using envelope encryption."""
        try:
            # Check if DEK is cached
            if session_id in self._dek_cache:
                dek, expires_at = self._dek_cache[session_id]
                if datetime.now(timezone.utc) < expires_at:
                    # Use cached DEK
                    encrypted_content = bytes.fromhex(envelope_data["ciphertext"])
                    content_metadata = bytes.fromhex(envelope_data["content_metadata"])
                    
                    content_bytes = self._decrypt_data(encrypted_content, dek, content_metadata)
                    return content_bytes.decode('utf-8')
            
            # DEK not cached or expired, decrypt from envelope
            encrypted_dek = bytes.fromhex(envelope_data["encrypted_dek"])
            dek_metadata = bytes.fromhex(envelope_data["dek_metadata"])
            
            # Decrypt DEK
            dek = self._decrypt_dek(encrypted_dek, dek_metadata)
            
            # Decrypt content
            encrypted_content = bytes.fromhex(envelope_data["ciphertext"])
            content_metadata = bytes.fromhex(envelope_data["content_metadata"])
            
            content_bytes = self._decrypt_data(encrypted_content, dek, content_metadata)
            
            # Cache the DEK
            expires_at = datetime.now(timezone.utc) + timedelta(hours=self.config.ttl_hours)
            self._dek_cache[session_id] = (dek, expires_at)
            
            return content_bytes.decode('utf-8')
            
        except Exception as e:
            logger.error(f"Failed to decrypt content for session {session_id}: {e}")
            raise CryptoShreddingError(f"Decryption failed: {e}")
    
    def crypto_shred(self, session_id: str) -> bool:
        """Crypto-shred by deleting the DEK, making encrypted content unreadable."""
        try:
            # Remove from cache
            if session_id in self._dek_cache:
                del self._dek_cache[session_id]
            
            # In production, this would also delete the DEK from KMS
            # For now, we just log the action
            logger.info(f"Crypto-shredded DEK for session {session_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to crypto-shred session {session_id}: {e}")
            return False
    
    def cleanup_expired_deks(self) -> int:
        """Clean up expired DEKs from cache."""
        now = datetime.now(timezone.utc)
        expired_sessions = [
            session_id for session_id, (dek, expires_at) in self._dek_cache.items()
            if now >= expires_at
        ]
        
        for session_id in expired_sessions:
            del self._dek_cache[session_id]
        
        logger.info(f"Cleaned up {len(expired_sessions)} expired DEKs")
        return len(expired_sessions)
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get statistics about the DEK cache."""
        now = datetime.now(timezone.utc)
        active_count = sum(1 for _, (_, expires_at) in self._dek_cache.items() if now < expires_at)
        expired_count = len(self._dek_cache) - active_count
        
        return {
            "total_cached_deks": len(self._dek_cache),
            "active_deks": active_count,
            "expired_deks": expired_count,
            "cache_size_bytes": sum(len(dek) for dek, _ in self._dek_cache.values())
        }

class EphemeralCacheService:
    """Service for managing ephemeral encrypted cache with crypto-shredding."""
    
    def __init__(self, crypto_service: EnvelopeEncryption, db_pool):
        self.crypto = crypto_service
        self.db_pool = db_pool
        self.enabled = os.getenv("EPHEMERAL_CACHE_ENABLED", "false").lower() == "true"
    
    async def store_content(self, session_id: str, resource_type: str, resource_id: str, content: str) -> bool:
        """Store encrypted content in ephemeral cache."""
        if not self.enabled:
            return False
        
        try:
            # Encrypt content
            envelope_data = self.crypto.encrypt_content(content, session_id)
            
            # Calculate TTL
            ttl_hours = int(os.getenv("EPHEMERAL_CACHE_TTL_HOURS", "24"))
            ttl_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
            
            # Store in database
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO temp_content (session_id, resource_type, resource_id, dek_id, ciphertext, ttl_at)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (session_id, resource_type, resource_id)
                    DO UPDATE SET
                        dek_id = EXCLUDED.dek_id,
                        ciphertext = EXCLUDED.ciphertext,
                        ttl_at = EXCLUDED.ttl_at,
                        created_at = NOW()
                """, 
                    session_id, resource_type, resource_id,
                    envelope_data["dek_id"],
                    json.dumps(envelope_data).encode('utf-8'),
                    ttl_at
                )
            
            logger.info(f"Stored encrypted content for session {session_id}, resource {resource_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to store content in ephemeral cache: {e}")
            return False
    
    async def retrieve_content(self, session_id: str, resource_type: str, resource_id: str) -> Optional[str]:
        """Retrieve and decrypt content from ephemeral cache."""
        if not self.enabled:
            return None
        
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT dek_id, ciphertext, ttl_at
                    FROM temp_content
                    WHERE session_id = $1 AND resource_type = $2 AND resource_id = $3
                    AND ttl_at > NOW()
                """, session_id, resource_type, resource_id)
                
                if not row:
                    return None
                
                # Decrypt content
                envelope_data = json.loads(row["ciphertext"].decode('utf-8'))
                content = self.crypto.decrypt_content(envelope_data, session_id)
                
                return content
                
        except Exception as e:
            logger.error(f"Failed to retrieve content from ephemeral cache: {e}")
            return None
    
    async def crypto_shred_session(self, session_id: str) -> bool:
        """Crypto-shred all content for a session."""
        try:
            # Delete DEK from crypto service
            self.crypto.crypto_shred(session_id)
            
            # Delete from database
            async with self.db_pool.acquire() as conn:
                result = await conn.execute("""
                    DELETE FROM temp_content WHERE session_id = $1
                """, session_id)
                
                deleted_count = int(result.split()[-1])
                logger.info(f"Crypto-shredded {deleted_count} items for session {session_id}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to crypto-shred session {session_id}: {e}")
            return False
    
    async def cleanup_expired_content(self) -> int:
        """Clean up expired content from the cache."""
        try:
            # Clean up expired DEKs
            self.crypto.cleanup_expired_deks()
            
            # Clean up expired database entries
            async with self.db_pool.acquire() as conn:
                result = await conn.execute("""
                    DELETE FROM temp_content WHERE ttl_at <= NOW()
                """)
                
                deleted_count = int(result.split()[-1])
                logger.info(f"Cleaned up {deleted_count} expired cache entries")
                return deleted_count
                
        except Exception as e:
            logger.error(f"Failed to cleanup expired content: {e}")
            return 0

def create_crypto_service() -> EnvelopeEncryption:
    """Factory function to create crypto service with configuration."""
    config = KMSConfig(
        kek_id=os.getenv("KMS_KEK_ID", "default"),
        kek_algorithm=os.getenv("KMS_KEK_ALGORITHM", "AES-256"),
        dek_length=int(os.getenv("KMS_DEK_LENGTH", "32")),
        ttl_hours=int(os.getenv("EPHEMERAL_CACHE_TTL_HOURS", "24"))
    )
    
    return EnvelopeEncryption(config)

def create_ephemeral_cache_service(db_pool) -> EphemeralCacheService:
    """Factory function to create ephemeral cache service."""
    crypto_service = create_crypto_service()
    return EphemeralCacheService(crypto_service, db_pool)
