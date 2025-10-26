from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Any

from pydantic import Field

from .enums import UserRole, UserStatus
from .mixins import FrozenModel

class User(FrozenModel):
    user_id: str
    username: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: UserRole
    status: UserStatus = Field(default=UserStatus.ACTIVE)
    department: Optional[str] = None
    license_number: Optional[str] = None
    phone: Optional[str] = None
    hsa_id: Optional[str] = None  # HSA ID for SITHS authentication whitelist
    siths_metadata: dict = Field(default_factory=dict)  # SITHS certificate metadata
    # Note: last_login is tracked in UserSession table for proper audit logging

    @property
    def full_name(self) -> str:
        """Returns the full name of the user."""
        return f"{self.first_name or ''} {self.last_name or ''}".strip()
    
    @property
    def is_active(self) -> bool:
        """Returns True if the user is active."""
        return self.status == UserStatus.ACTIVE
    
    @property
    def display_name(self) -> str:
        """Returns a display name for the user, falling back to username if no full name."""
        return f"Dr. {self.full_name}" if self.role == UserRole.DOCTOR else self.full_name
    
    @property 
    def is_admin(self) -> bool:
        """Returns True if the user has admin privileges."""
        return self.role == UserRole.ADMIN 
    

class UserSession(FrozenModel):
    """User session information."""
    session_id: str
    user_id: str
    login_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    is_active: bool = True


class UserAction(FrozenModel):
    """Represents an action performed by a user."""
    action_id: str
    user_id: str
    action_type: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    description: str
    metadata: dict = Field(default_factory=dict)


class UserEHRConnection(FrozenModel):
    """Represents a connection to an EHR system for a user."""
    connection_id: str
    user_id: str
    provider_type: str
    fhir_server_url: str
    client_id: str
    credentials: dict[str, Any]
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_expires_at: Optional[datetime] = None
    scope: Optional[str] = None
    patient_context: Optional[str] = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    
    




    