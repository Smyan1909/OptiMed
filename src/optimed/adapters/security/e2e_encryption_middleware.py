"""
End-to-End Encryption Middleware for OptiMed

Provides comprehensive encryption for all data flows in the application.
"""

import json
import time
from typing import Dict, Any, Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from .encryption_service import (
    get_encryption_service,
    encrypt_api_response,
    decrypt_api_request,
    encrypt_patient_data,
    decrypt_patient_data
)
from optimed.core.logging_utils import get_logger, log_error

logger = get_logger(__name__)

class E2EEncryptionMiddleware(BaseHTTPMiddleware):
    """End-to-end encryption middleware for all API communications."""
    
    def __init__(self, app, encrypt_responses: bool = True, encrypt_requests: bool = True):
        super().__init__(app)
        self.encrypt_responses = encrypt_responses
        self.encrypt_requests = encrypt_requests
        self.encryption_service = get_encryption_service()
        
        # Routes that should always be encrypted
        self.encrypted_routes = {
            "/chat-history",
            "/diagnose",
            "/info-relay", 
            "/patients/",
            "/analytics/",
            "/api/chat",
            "/api/diagnose"
        }
        
        # Routes that should never be encrypted (health checks, etc.)
        self.excluded_routes = {
            "/health",
            "/docs",
            "/openapi.json",
            "/favicon.ico"
        }
        
        # Routes that use streaming responses (should not be encrypted)
        self.streaming_routes = {
            "/diagnose/stream",
            "/chat/stream",
            "/stream",
            "/api/diagnose/stream",
            "/api/chat/stream"
        }
    
    async def dispatch(self, request: Request, call_next):
        """Process request and response with end-to-end encryption."""
        start_time = time.time()
        
        # Skip encryption for excluded routes and streaming routes
        if (any(request.url.path.startswith(route) for route in self.excluded_routes) or
            any(request.url.path.startswith(route) for route in self.streaming_routes)):
            logger.info(f"Bypassing encryption for route: {request.url.path}")
            response = await call_next(request)
            return response
        
        # Decrypt incoming request if needed
        if self.encrypt_requests and self._should_encrypt_route(request.url.path):
            try:
                # Read request body
                body = await request.body()
                if body:
                    request_data = json.loads(body)
                    decrypted_data = decrypt_api_request(request_data)
                    
                    # Replace request body with decrypted data
                    new_body = json.dumps(decrypted_data).encode()
                    
                    # Create new request with decrypted body
                    scope = dict(request.scope)
                    scope["headers"] = [
                        (k, v) for k, v in scope["headers"]
                        if k.lower() != b"content-length"
                    ]
                    scope["headers"].append((b"content-length", str(len(new_body)).encode()))
                    
                    # Create new request object
                    request = Request(scope, receive=self._create_receive(new_body))

                    # Log encryption audit event (GDPR Article 32 compliance)
                    if hasattr(request.app.state, '_audit_repo'):
                        try:
                            audit_repo = request.app.state._audit_repo
                            user = getattr(request.state, 'user', None)
                            await audit_repo.log_usage_metric(
                                metric_type="encryption",
                                metric_name="request_decrypted",
                                value=len(body),
                                unit="bytes",
                                dimensions={
                                    "algorithm": "AES-256-GCM",
                                    "endpoint": request.url.path,
                                    "success": True,
                                    "user_id": user.user_id if user else None
                                }
                            )
                        except Exception as audit_error:
                            log_error(logger, "Encryption audit logging", audit_error)

            except Exception as e:
                log_error(logger, "Request decryption", e)
                # Log failed decryption
                if hasattr(request.app.state, '_audit_repo'):
                    try:
                        audit_repo = request.app.state._audit_repo
                        await audit_repo.log_usage_metric(
                            metric_type="encryption",
                            metric_name="request_decryption_failed",
                            value=1,
                            unit="count",
                            dimensions={
                                "endpoint": request.url.path,
                                "error": str(e)
                            }
                        )
                    except:
                        pass
                # Continue with original request if decryption fails
        
        # Process the request
        response = await call_next(request)
        
        # Encrypt outgoing response if needed (skip for streaming responses)
        logger.info(f"Response media type: {response.media_type}, path: {request.url.path}")
        is_streaming = (response.media_type == "text/event-stream" or
                       hasattr(response, 'body_iterator') and
                       hasattr(response.body_iterator, '__aiter__'))

        if (self.encrypt_responses and
            self._should_encrypt_route(request.url.path) and
            not is_streaming):
            try:
                # Read response body
                response_body = b""
                async for chunk in response.body_iterator:
                    response_body += chunk
                
                if response_body:
                    # Parse and encrypt response
                    response_data = json.loads(response_body)
                    encrypted_response = encrypt_api_response(response_data)
                    
                    # Create new response with encrypted data
                    new_response_body = json.dumps(encrypted_response).encode()

                    # Add encryption headers
                    headers = dict(response.headers)
                    headers["X-Encrypted"] = "true"
                    headers["X-Encryption-Version"] = "1.0"
                    headers["X-Encryption-Timestamp"] = str(int(time.time() * 1000))

                    # Update Content-Length to match encrypted response size
                    headers["Content-Length"] = str(len(new_response_body))

                    # Log encryption audit event (GDPR Article 32 compliance)
                    if hasattr(request.app.state, '_audit_repo'):
                        try:
                            audit_repo = request.app.state._audit_repo
                            user = getattr(request.state, 'user', None)
                            await audit_repo.log_usage_metric(
                                metric_type="encryption",
                                metric_name="response_encrypted",
                                value=len(new_response_body),
                                unit="bytes",
                                dimensions={
                                    "algorithm": "AES-256-GCM",
                                    "endpoint": request.url.path,
                                    "success": True,
                                    "user_id": user.user_id if user else None
                                }
                            )
                        except Exception as audit_error:
                            log_error(logger, "Encryption audit logging", audit_error)

                    return Response(
                        content=new_response_body,
                        status_code=response.status_code,
                        headers=headers,
                        media_type=response.media_type
                    )

            except Exception as e:
                log_error(logger, "Response encryption", e)
                # Log failed encryption
                if hasattr(request.app.state, '_audit_repo'):
                    try:
                        audit_repo = request.app.state._audit_repo
                        await audit_repo.log_usage_metric(
                            metric_type="encryption",
                            metric_name="response_encryption_failed",
                            value=1,
                            unit="count",
                            dimensions={
                                "endpoint": request.url.path,
                                "error": str(e)
                            }
                        )
                    except:
                        pass
                # Return original response if encryption fails
        
        # Add security headers to all responses
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        # Log request processing time
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        
        return response
    
    def _should_encrypt_route(self, path: str) -> bool:
        """Determine if a route should be encrypted."""
        return any(path.startswith(route) for route in self.encrypted_routes)
    
    def _create_receive(self, body: bytes):
        """Create a receive function for the request body."""
        async def receive() -> Dict[str, Any]:
            return {"type": "http.request", "body": body}
        return receive

class SessionEncryptionManager:
    """Manages session-specific encryption keys."""
    
    def __init__(self):
        self.session_keys: Dict[str, str] = {}
        self.encryption_service = get_encryption_service()
    
    def generate_session_key(self, session_id: str) -> str:
        """Generate a unique encryption key for a session."""
        session_key = self.encryption_service.generate_session_key()
        self.session_keys[session_id] = session_key
        return session_key
    
    def get_session_key(self, session_id: str) -> Optional[str]:
        """Get the encryption key for a session."""
        return self.session_keys.get(session_id)
    
    def encrypt_session_data(self, session_id: str, data: Dict[str, Any]) -> str:
        """Encrypt data using session-specific key."""
        session_key = self.get_session_key(session_id)
        if session_key:
            return encrypt_patient_data(data, session_key)
        else:
            return encrypt_patient_data(data)  # Fallback to master key
    
    def decrypt_session_data(self, session_id: str, encrypted_data: str) -> Dict[str, Any]:
        """Decrypt data using session-specific key."""
        session_key = self.get_session_key(session_id)
        if session_key:
            return decrypt_patient_data(encrypted_data, session_key)
        else:
            return decrypt_patient_data(encrypted_data)  # Fallback to master key
    
    def clear_session_key(self, session_id: str) -> None:
        """Clear session key for security."""
        if session_id in self.session_keys:
            del self.session_keys[session_id]

    def setup_session_encryption(self, session_id: str, client_public_key_pem: str) -> str:
        """Setup session encryption with key exchange."""
        session_key = self.generate_session_key(session_id)
        # Encrypt session key with client's public key
        encrypted_key = self.encryption_service.encrypt_session_key_for_client(
            session_key.encode(), client_public_key_pem
        )
        return encrypted_key

# Global session encryption manager
_session_encryption_manager: Optional[SessionEncryptionManager] = None

def get_session_encryption_manager() -> SessionEncryptionManager:
    """Get global session encryption manager."""
    global _session_encryption_manager
    if _session_encryption_manager is None:
        _session_encryption_manager = SessionEncryptionManager()
    return _session_encryption_manager

def create_session_with_encryption(session_id: str, client_public_key_pem: Optional[str] = None) -> Dict[str, str]:
    """Create a new encrypted session with key exchange."""
    manager = get_session_encryption_manager()

    result = {
        "session_id": session_id,
        "encrypted": "true",
        "version": "2.0"
    }

    if client_public_key_pem:
        # Perform key exchange
        encrypted_session_key = manager.setup_session_encryption(session_id, client_public_key_pem)
        result["encrypted_session_key"] = encrypted_session_key

        # Provide server public key for client
        encryption_service = get_encryption_service()
        result["server_public_key"] = encryption_service.get_public_key_pem()
    else:
        # Generate session key without key exchange (less secure)
        manager.generate_session_key(session_id)

    return result
