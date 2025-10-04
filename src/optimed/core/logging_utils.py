"""
Logging utilities for OptiMed.

Provides GDPR-compliant logging that sanitizes sensitive information.
Uses Python's standard logging module with async-safe practices.
"""

import logging
import sys
import hashlib
from typing import Any, Optional
from pathlib import Path

# GDPR-compliant logging configuration
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a module.

    Args:
        name: Module name (typically __name__)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Only configure if not already configured
    if not logger.handlers:
        logger.setLevel(logging.INFO)

        # Console handler
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)

        # Formatter
        formatter = logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT)
        handler.setFormatter(formatter)

        logger.addHandler(handler)

    return logger


def sanitize_id(value: str, prefix: str = "ID") -> str:
    """
    Sanitize an ID for logging by hashing it.

    Args:
        value: The ID to sanitize
        prefix: Prefix for the sanitized value

    Returns:
        Sanitized string like "ID_abc123..."
    """
    if not value:
        return f"{prefix}_none"

    # Hash the value and take first 8 characters
    hashed = hashlib.sha256(value.encode()).hexdigest()[:8]
    return f"{prefix}_{hashed}"


def sanitize_user_id(user_id: Optional[str]) -> str:
    """Sanitize user ID for logging."""
    return sanitize_id(user_id or "", "user")


def sanitize_patient_id(patient_id: Optional[str]) -> str:
    """Sanitize patient ID for logging."""
    return sanitize_id(patient_id or "", "patient")


def sanitize_session_id(session_id: Optional[str]) -> str:
    """Sanitize session ID for logging."""
    return sanitize_id(session_id or "", "session")


def sanitize_document_id(document_id: Optional[str]) -> str:
    """Sanitize document ID for logging."""
    return sanitize_id(document_id or "", "doc")


def log_operation(logger: logging.Logger, operation: str, **kwargs: Any) -> None:
    """
    Log an operation with sanitized parameters.

    Args:
        logger: Logger instance
        operation: Operation name
        **kwargs: Key-value pairs to log (will be sanitized if needed)
    """
    # Sanitize known sensitive fields
    sanitized = {}
    for key, value in kwargs.items():
        if 'user_id' in key.lower():
            sanitized[key] = sanitize_user_id(str(value) if value else None)
        elif 'patient_id' in key.lower():
            sanitized[key] = sanitize_patient_id(str(value) if value else None)
        elif 'session_id' in key.lower():
            sanitized[key] = sanitize_session_id(str(value) if value else None)
        elif 'document_id' in key.lower():
            sanitized[key] = sanitize_document_id(str(value) if value else None)
        else:
            # For other fields, just include them as-is if they're not sensitive
            sanitized[key] = value

    # Format the log message
    params = ", ".join(f"{k}={v}" for k, v in sanitized.items())
    logger.info(f"{operation}: {params}" if params else operation)


def log_error(logger: logging.Logger, operation: str, error: Exception, **kwargs: Any) -> None:
    """
    Log an error with sanitized context.

    Args:
        logger: Logger instance
        operation: Operation that failed
        error: The exception
        **kwargs: Additional context (will be sanitized)
    """
    # Sanitize context
    sanitized = {}
    for key, value in kwargs.items():
        if any(sensitive in key.lower() for sensitive in ['user_id', 'patient_id', 'session_id', 'document_id']):
            sanitized[key] = sanitize_id(str(value) if value else None, key.split('_')[0])
        else:
            sanitized[key] = value

    # Format error message
    error_msg = f"{operation} failed: {type(error).__name__}"
    if sanitized:
        context = ", ".join(f"{k}={v}" for k, v in sanitized.items())
        error_msg = f"{error_msg} ({context})"

    logger.error(error_msg)
