"""
Audit Logging Middleware for OptiMed API Gateway

Automatically logs all API requests/responses with GDPR-compliant metadata.
Tracks request categories, performance metrics, and data access patterns.
"""

import time
from typing import Optional, Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


def categorize_endpoint(path: str, method: str) -> str:
    """
    Categorize API endpoint for audit logging.

    Args:
        path: Request path
        method: HTTP method

    Returns:
        Category string
    """
    # Normalize path
    path_lower = path.lower()

    # Categorization rules
    if "/diagnose" in path_lower:
        return "diagnosis_support"
    elif "/chat" in path_lower:
        return "chat_interaction"
    elif "/journal" in path_lower:
        return "note_generation"
    elif "/dicom" in path_lower or "/images" in path_lower:
        return "image_analysis"
    elif "/patients" in path_lower or "/patient" in path_lower:
        return "ehr_access"
    elif "/documents" in path_lower or "/document" in path_lower:
        return "document_upload"
    elif "/lookup" in path_lower or "/search" in path_lower:
        return "information_lookup"
    elif "/auth" in path_lower:
        return "authentication"
    elif "/health" in path_lower or "/status" in path_lower:
        return "system_health"
    elif "/analytics" in path_lower or "/metrics" in path_lower:
        return "analytics_query"
    else:
        return "general_api"


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to automatically audit log all API requests.

    Captures request metadata, timing, and categorization.
    Ensures all logs are GDPR-compliant (no PHI stored).
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request, log audit trail, and pass to next handler.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler

        Returns:
            HTTP response
        """
        # Skip audit logging for public endpoints (to reduce noise)
        skip_paths = {"/health", "/docs", "/redoc", "/openapi.json", "/favicon.ico"}
        if request.url.path in skip_paths:
            return await call_next(request)

        # Start timing
        start_time = time.time()

        # Extract request metadata
        endpoint = request.url.path
        method = request.method
        session_id = request.headers.get("x-session-id")
        user_id = None

        # Get user from request state (set by auth middleware)
        if hasattr(request.state, "user") and request.state.user:
            user_id = request.state.user.user_id

        # Categorize request
        category = categorize_endpoint(endpoint, method)

        # Process request
        response = None
        error_message = None
        status_code = 500  # Default to error

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as e:
            # Capture error but let it propagate
            error_message = f"{type(e).__name__}: {str(e)}"
            status_code = 500
            raise
        finally:
            # Calculate latency
            latency_ms = int((time.time() - start_time) * 1000)

            # Log audit trail asynchronously (don't block response)
            try:
                await self._log_audit_trail(
                    session_id=session_id,
                    user_id=user_id,
                    endpoint=endpoint,
                    method=method,
                    status_code=status_code,
                    latency_ms=latency_ms,
                    category=category,
                    error_message=error_message,
                    request=request
                )
            except Exception as log_error:
                # Don't fail the request if logging fails
                print(f"[AUDIT_MIDDLEWARE] Error logging audit trail: {log_error}")

        return response

    async def _log_audit_trail(
        self,
        session_id: Optional[str],
        user_id: Optional[str],
        endpoint: str,
        method: str,
        status_code: int,
        latency_ms: int,
        category: str,
        error_message: Optional[str],
        request: Request
    ) -> None:
        """
        Log audit trail to database.

        Args:
            session_id: Session ID
            user_id: User ID
            endpoint: API endpoint
            method: HTTP method
            status_code: HTTP status code
            latency_ms: Request latency
            category: Request category
            error_message: Error message if failed
            request: Request object
        """
        try:
            # Get audit repository from app state
            if not hasattr(request.app.state, "_audit_repo"):
                print("[AUDIT_MIDDLEWARE] Audit repository not initialized")
                return

            audit_repo = request.app.state._audit_repo

            # Log API request
            await audit_repo.log_api_request(
                session_id=session_id,
                user_id=user_id,
                endpoint=endpoint,
                method=method,
                status_code=status_code,
                latency_ms=latency_ms,
                request_category=category,
                error_message=error_message,
                metadata={
                    "user_agent": request.headers.get("user-agent"),
                    "origin": request.headers.get("origin"),
                }
            )

            # Log performance metric
            if latency_ms > 1000:  # Log slow requests (>1s)
                await audit_repo.log_usage_metric(
                    metric_type="performance",
                    metric_name="slow_request",
                    value=latency_ms,
                    unit="milliseconds",
                    dimensions={
                        "endpoint": endpoint,
                        "category": category,
                        "status_code": status_code
                    }
                )

            # Log error metrics
            if status_code >= 400:
                await audit_repo.log_usage_metric(
                    metric_type="error",
                    metric_name="request_error",
                    value=1,
                    unit="count",
                    dimensions={
                        "endpoint": endpoint,
                        "status_code": status_code,
                        "category": category,
                        "error_type": error_message.split(":")[0] if error_message else "unknown"
                    }
                )

        except Exception as e:
            print(f"[AUDIT_MIDDLEWARE] Error in _log_audit_trail: {e}")


async def log_data_access_from_endpoint(
    request: Request,
    resource_type: str,
    resource_count: int = 1,
    data_source: str = "fhir",
    access_type: str = "read"
) -> None:
    """
    Helper function to log data access from within endpoint handlers.

    Use this in your endpoint code to log specific data access events.

    Example:
        @app.get("/patients/{patient_id}")
        async def get_patient(patient_id: str, request: Request):
            # Your logic here
            await log_data_access_from_endpoint(
                request, "Patient", 1, "fhir", "read"
            )
            return patient_data

    Args:
        request: FastAPI request
        resource_type: Type of resource (Patient, Observation, etc.)
        resource_count: Number of resources accessed
        data_source: Data source (fhir, database, etc.)
        access_type: Type of access (read, write, delete)
    """
    try:
        # Get user and session from request
        session_id = request.headers.get("x-session-id")
        user_id = None
        if hasattr(request.state, "user") and request.state.user:
            user_id = request.state.user.user_id

        if not user_id:
            return  # Skip if no user context

        # Get audit repository
        if not hasattr(request.app.state, "_audit_repo"):
            return

        audit_repo = request.app.state._audit_repo

        # Log data access
        await audit_repo.log_data_access(
            session_id=session_id,
            user_id=user_id,
            access_type=access_type,
            resource_type=resource_type,
            resource_count=resource_count,
            data_source=data_source,
            lawful_basis="care_delivery",
            purpose_of_use="clinical_decision_support"
        )

    except Exception as e:
        print(f"[AUDIT] Error logging data access: {e}")
