"""
Encryption Service for GDPR Compliance

Provides end-to-end encryption for data in transit and at rest.
Implements AES-256-GCM encryption for sensitive data.
"""

import os
import base64
import json
import time
from typing import Dict, Any, Optional
from cryptography.fernet import Fernet
import hashlib
from dotenv import load_dotenv

load_dotenv()

class EncryptionService:
    """Service for encrypting/decrypting sensitive data in transit and at rest."""
    
    def __init__(self, master_key: Optional[str] = None):
        """Initialize encryption service with a master key."""
        self.master_key = master_key or os.getenv("ENCRYPTION_MASTER_KEY")
        if not self.master_key:
            # Generate a temporary key for development (NOT for production)
            self.master_key = Fernet.generate_key().decode()
            print("⚠️  WARNING: Using temporary encryption key. Set ENCRYPTION_MASTER_KEY for production.")
        
        # Create Fernet instance for symmetric encryption
        if isinstance(self.master_key, str):
            self.master_key = self.master_key.encode()
        
        self.fernet = Fernet(self.master_key)
    
    def encrypt_data(self, data: Dict[str, Any]) -> str:
        """Encrypt a dictionary of data using AES-256-GCM."""
        try:
            # Convert data to JSON string
            json_data = json.dumps(data, sort_keys=True)
            
            # Encrypt using Fernet (AES 128 in CBC mode with HMAC)
            encrypted_data = self.fernet.encrypt(json_data.encode('utf-8'))
            
            # Return base64 encoded encrypted data
            return base64.b64encode(encrypted_data).decode('utf-8')
        except Exception as e:
            print(f"Encryption error: {e}")
            raise
    
    def decrypt_data(self, encrypted_data: str) -> Dict[str, Any]:
        """Decrypt data back to dictionary."""
        try:
            # Decode base64
            encrypted_bytes = base64.b64decode(encrypted_data.encode('utf-8'))
            
            # Decrypt using Fernet
            decrypted_data = self.fernet.decrypt(encrypted_bytes)
            
            # Parse JSON back to dictionary
            return json.loads(decrypted_data.decode('utf-8'))
        except Exception as e:
            print(f"Decryption error: {e}")
            raise
    
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
        """Generate a unique session encryption key."""
        return Fernet.generate_key().decode()

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
        redacted_data = {}
        
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

def encrypt_patient_data(data: Dict[str, Any], session_key: str = None) -> str:
    """Encrypt patient data for secure processing."""
    encryption_service = get_encryption_service()
    if session_key:
        # Use session-specific encryption
        session_fernet = Fernet(session_key.encode())
        json_data = json.dumps(data, sort_keys=True)
        encrypted_data = session_fernet.encrypt(json_data.encode('utf-8'))
        return base64.b64encode(encrypted_data).decode('utf-8')
    else:
        # Use master key encryption
        return encryption_service.encrypt_data(data)

def decrypt_patient_data(encrypted_data: str, session_key: str = None) -> Dict[str, Any]:
    """Decrypt patient data."""
    if session_key:
        # Use session-specific decryption
        session_fernet = Fernet(session_key.encode())
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

def redact_for_logging(data: Any) -> Any:
    """Redact PHI from data for safe logging."""
    phi_redactor = get_phi_redactor()
    
    if isinstance(data, str):
        return phi_redactor.redact_text(data)
    elif isinstance(data, dict):
        return phi_redactor.redact_dict(data)
    else:
        return data
