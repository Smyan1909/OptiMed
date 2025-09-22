"""
Encryption Service for GDPR Compliance

Provides end-to-end encryption for data in transit and at rest.
Implements AES-256-GCM encryption for sensitive data.
"""

import os
import base64
import json
import time
import secrets
from typing import Dict, Any, Optional, Tuple
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.backends import default_backend
from cryptography.fernet import Fernet
import hashlib
from dotenv import load_dotenv

load_dotenv()

class EncryptionService:
    """Advanced E2E encryption service using AES-256-GCM with RSA key exchange."""

    def __init__(self, master_key: Optional[str] = None):
        """Initialize encryption service with master key and RSA keypair."""
        self.master_key = master_key or os.getenv("ENCRYPTION_MASTER_KEY")
        if not self.master_key:
            # Generate a temporary key for development (NOT for production)
            self.master_key = Fernet.generate_key().decode()
            print("⚠️  WARNING: Using temporary encryption key. Set ENCRYPTION_MASTER_KEY for production.")

        # Legacy Fernet for backward compatibility
        if isinstance(self.master_key, str):
            self.master_key_bytes = self.master_key.encode()
        else:
            self.master_key_bytes = self.master_key

        self.fernet = Fernet(self.master_key_bytes)

        # Generate RSA keypair for secure key exchange
        self.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )
        self.public_key = self.private_key.public_key()

        # Session key cache with TTL
        self.session_keys: Dict[str, Tuple[str, float]] = {}
        self.session_key_ttl = 3600  # 1 hour TTL
    
    def encrypt_data_aes_gcm(self, data: Dict[str, Any], session_key: Optional[bytes] = None) -> str:
        """Encrypt data using AES-256-GCM for maximum security."""
        try:
            # Convert data to JSON
            json_data = json.dumps(data, sort_keys=True).encode('utf-8')

            # Use session key or derive from master key
            if session_key:
                key = session_key[:32]  # AES-256 requires 32 bytes
            else:
                key = self._derive_key_from_master()[:32]

            # Generate random IV (12 bytes for GCM)
            iv = secrets.token_bytes(12)

            # Create cipher
            cipher = Cipher(algorithms.AES(key), modes.GCM(iv), backend=default_backend())
            encryptor = cipher.encryptor()

            # Encrypt data
            ciphertext = encryptor.update(json_data) + encryptor.finalize()

            # Combine IV + tag + ciphertext
            encrypted_data = iv + encryptor.tag + ciphertext

            return base64.b64encode(encrypted_data).decode('utf-8')
        except Exception as e:
            print(f"AES-GCM encryption error: {e}")
            raise

    def encrypt_data(self, data: Dict[str, Any]) -> str:
        """Legacy method - redirects to AES-GCM encryption."""
        return self.encrypt_data_aes_gcm(data)
    
    def decrypt_data_aes_gcm(self, encrypted_data: str, session_key: Optional[bytes] = None) -> Dict[str, Any]:
        """Decrypt AES-256-GCM encrypted data."""
        try:
            # Decode base64
            encrypted_bytes = base64.b64decode(encrypted_data.encode('utf-8'))

            # Extract components
            iv = encrypted_bytes[:12]  # First 12 bytes
            tag = encrypted_bytes[12:28]  # Next 16 bytes
            ciphertext = encrypted_bytes[28:]  # Remaining bytes

            # Use session key or derive from master key
            if session_key:
                key = session_key[:32]
            else:
                key = self._derive_key_from_master()[:32]

            # Create cipher
            cipher = Cipher(algorithms.AES(key), modes.GCM(iv, tag), backend=default_backend())
            decryptor = cipher.decryptor()

            # Decrypt data
            decrypted_data = decryptor.update(ciphertext) + decryptor.finalize()

            # Parse JSON
            return json.loads(decrypted_data.decode('utf-8'))
        except Exception as e:
            print(f"AES-GCM decryption error: {e}")
            # Fallback to legacy Fernet decryption
            try:
                return self._decrypt_data_legacy(encrypted_data)
            except Exception:
                raise e

    def decrypt_data(self, encrypted_data: str) -> Dict[str, Any]:
        """Legacy method with fallback support."""
        return self.decrypt_data_aes_gcm(encrypted_data)

    def _decrypt_data_legacy(self, encrypted_data: str) -> Dict[str, Any]:
        """Legacy Fernet decryption for backward compatibility."""
        encrypted_bytes = base64.b64decode(encrypted_data.encode('utf-8'))
        decrypted_data = self.fernet.decrypt(encrypted_bytes)
        return json.loads(decrypted_data.decode('utf-8'))
    
    def encrypt_string(self, text: str) -> str:
        """Encrypt a plain text string."""
        try:
            encrypted_data = self.fernet.encrypt(text.encode('utf-8'))
            return base64.b64encode(encrypted_data).decode('utf-8')
        except Exception as e:
            print(f"String encryption error: {e}")
            raise
    
    def decrypt_string(self, encrypted_text: str) -> str:
        """Decrypt an encrypted string."""
        try:
            encrypted_bytes = base64.b64decode(encrypted_text.encode('utf-8'))
            decrypted_data = self.fernet.decrypt(encrypted_bytes)
            return decrypted_data.decode('utf-8')
        except Exception as e:
            print(f"String decryption error: {e}")
            raise
    
    def hash_sensitive_data(self, data: str) -> str:
        """Create a one-way hash of sensitive data for logging/tracking."""
        # Use SHA-256 with a salt for hashing
        salt = os.getenv("HASH_SALT", "default_salt_change_in_production")
        combined = f"{data}{salt}".encode('utf-8')
        return hashlib.sha256(combined).hexdigest()
    
    def generate_session_key(self) -> str:
        """Generate a cryptographically secure 256-bit session key for Fernet."""
        # Use Fernet.generate_key() which creates properly formatted base64-encoded key
        from cryptography.fernet import Fernet
        return Fernet.generate_key().decode('utf-8')

    def store_session_key(self, session_id: str, key: str) -> None:
        """Store session key with TTL."""
        self.session_keys[session_id] = (key, time.time() + self.session_key_ttl)

    def get_session_key(self, session_id: str) -> Optional[bytes]:
        """Get session key if valid and not expired."""
        if session_id in self.session_keys:
            key, expiry = self.session_keys[session_id]
            if time.time() < expiry:
                return key.encode() if isinstance(key, str) else key
            else:
                del self.session_keys[session_id]  # Remove expired key
        return None

    def encrypt_session_key_for_client(self, session_key: bytes, client_public_key_pem: str) -> str:
        """Encrypt session key with client's public key for secure key exchange."""
        try:
            # Load client public key
            client_public_key = serialization.load_pem_public_key(
                client_public_key_pem.encode('utf-8'),
                backend=default_backend()
            )

            # Encrypt session key with client's public key
            encrypted_key = client_public_key.encrypt(
                session_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )

            return base64.b64encode(encrypted_key).decode('utf-8')
        except Exception as e:
            print(f"Session key encryption error: {e}")
            raise

    def decrypt_session_key_from_client(self, encrypted_session_key: str) -> bytes:
        """Decrypt session key using server's private key."""
        try:
            encrypted_key = base64.b64decode(encrypted_session_key.encode('utf-8'))

            session_key = self.private_key.decrypt(
                encrypted_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )

            return session_key
        except Exception as e:
            print(f"Session key decryption error: {e}")
            raise

    def get_public_key_pem(self) -> str:
        """Get server's public key in PEM format for client key exchange."""
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')

    def _derive_key_from_master(self) -> bytes:
        """Derive AES key from master key using PBKDF2."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'optimed_salt_2024',  # Use a consistent salt
            iterations=100000,
            backend=default_backend()
        )
        return kdf.derive(self.master_key_bytes)

class PHIRedactor:
    """Redacts PHI from data for logging and analytics."""
    
    # Common PHI patterns
    PHI_PATTERNS = [
        r'\b\d{3}-\d{2}-\d{4}\b',  # SSN
        r'\b\d{3}\.\d{2}\.\d{4}\b',  # SSN with dots
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # Email
        r'\b\d{3}-\d{3}-\d{4}\b',  # Phone
        r'\b\d{10}\b',  # 10-digit number (could be phone)
        r'\b[A-Z][a-z]+ [A-Z][a-z]+\b',  # Name pattern (First Last)
        r'\b\d{4}-\d{2}-\d{2}\b',  # Date (YYYY-MM-DD)
        r'\b\d{2}/\d{2}/\d{4}\b',  # Date (MM/DD/YYYY)
    ]
    
    def __init__(self):
        import re
        self.compiled_patterns = [re.compile(pattern) for pattern in self.PHI_PATTERNS]
    
    def redact_text(self, text: str) -> str:
        """Redact PHI from text for logging."""
        redacted_text = text
        
        for pattern in self.compiled_patterns:
            if pattern.pattern.startswith(r'\b[A-Z][a-z]+ [A-Z][a-z]+\b'):
                # Special handling for names - be more conservative
                redacted_text = pattern.sub('[NAME_REDACTED]', redacted_text)
            else:
                redacted_text = pattern.sub('[PHI_REDACTED]', redacted_text)
        
        return redacted_text
    
    def redact_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Redact PHI from dictionary data."""
        redacted_data: Dict[str, Any] = {}
        
        for key, value in data.items():
            if isinstance(value, str):
                redacted_data[key] = self.redact_text(value)
            elif isinstance(value, dict):
                redacted_data[key] = self.redact_dict(value)
            elif isinstance(value, list):
                redacted_data[key] = [
                    self.redact_dict(item) if isinstance(item, dict) 
                    else self.redact_text(item) if isinstance(item, str)
                    else item for item in value
                ]
            else:
                redacted_data[key] = value
        
        return redacted_data

# Global instances
_encryption_service: Optional[EncryptionService] = None
_phi_redactor: Optional[PHIRedactor] = None

def get_encryption_service() -> EncryptionService:
    """Get global encryption service instance."""
    global _encryption_service
    if _encryption_service is None:
        _encryption_service = EncryptionService()
    return _encryption_service

def get_phi_redactor() -> PHIRedactor:
    """Get global PHI redactor instance."""
    global _phi_redactor
    if _phi_redactor is None:
        _phi_redactor = PHIRedactor()
    return _phi_redactor

def encrypt_api_response(data: Dict[str, Any]) -> Dict[str, Any]:
    """Encrypt API response data for transmission."""
    encryption_service = get_encryption_service()
    return {
        "encrypted": True,
        "data": encryption_service.encrypt_data(data),
        "timestamp": str(int(time.time() * 1000)),
        "version": "1.0"
    }

def decrypt_api_request(encrypted_data: Dict[str, Any]) -> Dict[str, Any]:
    """Decrypt API request data."""
    if encrypted_data.get("encrypted"):
        encryption_service = get_encryption_service()
        return encryption_service.decrypt_data(encrypted_data["data"])
    return encrypted_data

def encrypt_patient_data(data: Dict[str, Any], session_key: Optional[str] = None) -> str:
    """Encrypt patient data for secure processing."""
    encryption_service = get_encryption_service()
    if session_key:
        # Use session-specific encryption with Fernet-compatible key
        session_fernet = Fernet(session_key.encode('utf-8'))
        json_data = json.dumps(data, sort_keys=True)
        encrypted_data = session_fernet.encrypt(json_data.encode('utf-8'))
        return base64.b64encode(encrypted_data).decode('utf-8')
    else:
        # Use master key encryption
        return encryption_service.encrypt_data(data)

def decrypt_patient_data(encrypted_data: str, session_key: Optional[str] = None) -> Dict[str, Any]:
    """Decrypt patient data."""
    if session_key:
        # Use session-specific decryption with Fernet-compatible key
        session_fernet = Fernet(session_key.encode('utf-8'))
        encrypted_bytes = base64.b64decode(encrypted_data.encode('utf-8'))
        decrypted_data = session_fernet.decrypt(encrypted_bytes)
        return json.loads(decrypted_data.decode('utf-8'))
    else:
        # Use master key decryption
        encryption_service = get_encryption_service()
        return encryption_service.decrypt_data(encrypted_data)

def encrypt_model_request(data: Dict[str, Any]) -> Dict[str, Any]:
    """Encrypt data before sending to external models."""
    encryption_service = get_encryption_service()
    return {
        "encrypted": True,
        "data": encryption_service.encrypt_data(data),
        "model_safe": True
    }

def decrypt_model_response(encrypted_data: Dict[str, Any]) -> Dict[str, Any]:
    """Decrypt response from external models."""
    if encrypted_data.get("encrypted"):
        encryption_service = get_encryption_service()
        return encryption_service.decrypt_data(encrypted_data["data"])
    return encrypted_data

def encrypt_stream_chunk(chunk: str, session_key: bytes) -> str:
    """Encrypt individual SSE stream chunks for secure transmission."""
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend
        import secrets

        # Create cipher for stream encryption
        iv = secrets.token_bytes(12)
        key = session_key[:32] if len(session_key) >= 32 else session_key + b'\x00' * (32 - len(session_key))

        cipher = Cipher(algorithms.AES(key), modes.GCM(iv), backend=default_backend())
        encryptor = cipher.encryptor()

        # Encrypt chunk
        chunk_bytes = chunk.encode('utf-8')
        ciphertext = encryptor.update(chunk_bytes) + encryptor.finalize()

        # Combine IV + tag + ciphertext and base64 encode
        encrypted_data = iv + encryptor.tag + ciphertext
        return base64.b64encode(encrypted_data).decode('utf-8')
    except Exception as e:
        print(f"Stream chunk encryption error: {e}")
        return chunk  # Return original chunk if encryption fails

def decrypt_stream_chunk(encrypted_chunk: str, session_key: bytes) -> str:
    """Decrypt SSE stream chunks."""
    try:
        # Decode base64
        encrypted_data = base64.b64decode(encrypted_chunk.encode('utf-8'))

        # Extract components
        iv = encrypted_data[:12]
        tag = encrypted_data[12:28]
        ciphertext = encrypted_data[28:]

        # Prepare key
        key = session_key[:32] if len(session_key) >= 32 else session_key + b'\x00' * (32 - len(session_key))

        # Decrypt
        cipher = Cipher(algorithms.AES(key), modes.GCM(iv, tag), backend=default_backend())
        decryptor = cipher.decryptor()

        decrypted_data = decryptor.update(ciphertext) + decryptor.finalize()
        return decrypted_data.decode('utf-8')
    except Exception as e:
        print(f"Stream chunk decryption error: {e}")
        return encrypted_chunk  # Return as-is if decryption fails

def redact_for_logging(data: Any) -> Any:
    """Redact PHI from data for safe logging."""
    phi_redactor = get_phi_redactor()

    if isinstance(data, str):
        return phi_redactor.redact_text(data)
    elif isinstance(data, dict):
        return phi_redactor.redact_dict(data)
    else:
        return data
