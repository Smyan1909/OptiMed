from __future__ import annotations
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

from optimed.core.domain import UserEHRConnection, User
from optimed.core.ports import UserEHRConnectionRepository, AuthenticationProvider, FHIRRepository
from optimed.adapters.smart_fhir.auth_provider import SMARTAuthProvider

class UserEHRConnectionService:
    """Service for managing user EHR connections."""
    
    def __init__(self, connection_repo: UserEHRConnectionRepository):
        self._connection_repo = connection_repo
        self._auth_providers: Dict[str, AuthenticationProvider] = {}
        self._active_repositories: Dict[str, FHIRRepository] = {}
    
    def register_auth_provider(self, provider_type: str, provider: AuthenticationProvider):
        """Register an authentication provider for a specific type."""
        self._auth_providers[provider_type] = provider
    
    async def initiate_connection(
        self, 
        user: User, 
        provider_type: str,
        fhir_server_url: str,
        client_id: str,
        **kwargs: Any    ) -> Dict[str, Any]:
        """Initiate a new EHR connection using the registered auth provider."""
        if provider_type not in self._auth_providers:
            # Create SMART auth provider on demand if not registered
            if provider_type == "smart_fhir":
                # Extract constructor args from kwargs
                auth_kwargs = {k: v for k, v in kwargs.items() 
                              if k in ['client_secret', 'redirect_uri', 'timeout']}
                auth_provider = SMARTAuthProvider(
                    fhir_server_url=fhir_server_url,
                    client_id=client_id,
                    **auth_kwargs
                )
                self._auth_providers[provider_type] = auth_provider
            else:
                raise ValueError(f"No auth provider registered for {provider_type}")
        
        connection_id = str(uuid.uuid4())
        auth_provider = self._auth_providers[provider_type]
        
        # Use the auth provider to initiate the flow
        auth_info = await auth_provider.initiate_auth_flow(
            state=connection_id,
            **kwargs
        )
        
        # Create temporary connection
        connection = UserEHRConnection(
            connection_id=connection_id,
            user_id=user.user_id,
            provider_type=provider_type,
            fhir_server_url=fhir_server_url,
            client_id=client_id,
            credentials={},  # Empty until auth complete
            scope=kwargs.get("scope"),
            is_active=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        
        await self._connection_repo.create_connection(connection)
        
        return {
            "connection_id": connection_id,
            **auth_info
        }
    
    async def complete_connection(
        self, 
        connection_id: str, 
        auth_code: str
    ) -> UserEHRConnection:
        """Complete the authentication flow using the auth provider."""
        connection = await self._connection_repo.get_connection_by_id(connection_id)
        if not connection:
            raise ValueError(f"Connection {connection_id} not found")
        
        auth_provider = self._auth_providers.get(connection.provider_type)
        if not auth_provider:
            # Create auth provider if not found (shouldn't happen normally)
            if connection.provider_type == "smart_fhir":
                auth_provider = SMARTAuthProvider(
                    fhir_server_url=connection.fhir_server_url,
                    client_id=connection.client_id
                )
                self._auth_providers[connection.provider_type] = auth_provider
            else:
                raise ValueError(f"No auth provider for {connection.provider_type}")        
        # Use the auth provider to complete the flow
        credentials = await auth_provider.complete_auth_flow(auth_code)
        
        expires_at = None
        if credentials.get("expires_in"):
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=credentials["expires_in"])
        
        # Update connection with credentials
        connection_data = connection.model_dump()
        connection_data.update({
            "credentials": credentials,
            "access_token": credentials.get("access_token"),
            "refresh_token": credentials.get("refresh_token"),
            "token_expires_at": expires_at,
            "patient_context": credentials.get("patient"),  # SMART patient context
            "is_active": True,
            "expires_at": expires_at,
            "updated_at": datetime.now(timezone.utc)        })
        
        updated_connection = UserEHRConnection(**connection_data)
        
        await self._connection_repo.update_connection(updated_connection)
        return updated_connection
    
    async def create_fhir_repository(self, user_id: str, provider_type: str = "smart_fhir") -> Optional[FHIRRepository]:
        """Create an authenticated FHIR repository for a user using their connection and auth provider."""
        print(f"[ConnectionService] Creating FHIR repository for user {user_id}, provider {provider_type}")
        
        # Get active connection for this user
        connection = await self._connection_repo.get_active_connection_by_user(user_id, provider_type)
        if not connection:
            print(f"[ConnectionService] No active {provider_type} connection found for user {user_id}")
            return None
        
        if not connection.access_token:
            print(f"[ConnectionService] Connection {connection.connection_id} has no access token")
            return None
        
        print(f"[ConnectionService] Found connection {connection.connection_id} with access token")
        
        # Check if we already have a repository for this connection
        if connection.connection_id in self._active_repositories:
            repo = self._active_repositories[connection.connection_id]
            print(f"[ConnectionService] Reusing existing repository for connection {connection.connection_id}")
            return repo
        
        # Create new repository based on provider type
        if provider_type == "smart_fhir":
            try:
                # Import your SMART FHIR repository class
                from optimed.adapters.smart_fhir.repository import SMARTFHIRRepository
                from optimed.adapters.smart_fhir.auth_provider import SMARTAuthProvider
                
                # Create auth provider
                auth_provider = SMARTAuthProvider(
                    fhir_server_url=connection.fhir_server_url,
                    client_id=connection.client_id
                )
                
                # Create repository
                repository = SMARTFHIRRepository(connection, auth_provider)
                
                # Cache the repository
                self._active_repositories[connection.connection_id] = repository
                print(f"[ConnectionService] Created new {provider_type} repository for user {user_id}")
                return repository
                
            except Exception as e:
                print(f"[ConnectionService] Failed to create {provider_type} repository: {e}")
                import traceback
                traceback.print_exc()
                return None
        
        print(f"[ConnectionService] Unsupported provider type: {provider_type}")
        return None