import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from optimed.core.domain import User, UserEHRConnection
from optimed.apps.orchestrator.connection_service import UserEHRConnectionService
from optimed.adapters.smart_fhir.auth_provider import SMARTAuthProvider

class TestUserEHRConnectionService:
    """Unit tests for UserEHRConnectionService."""
    
    @pytest.fixture
    def mock_connection_repo(self):
        return AsyncMock()
    
    @pytest.fixture
    def connection_service(self, mock_connection_repo):
        return UserEHRConnectionService(mock_connection_repo)
    
    @pytest.fixture
    def test_user(self):
        return User(
            user_id="test_user_123",
            username="testuser",
            email="test@example.com",
            first_name="Test",
            last_name="User",
            role="doctor",
            status="active"        )
    
    async def test_initiate_connection_new_provider(self, connection_service, mock_connection_repo, test_user):
        """Test initiating connection with new auth provider."""
        mock_connection_repo.create_connection.return_value = AsyncMock()
        
        with patch('uuid.uuid4') as mock_uuid:
            mock_uuid.return_value = MagicMock()
            mock_uuid.return_value.__str__.return_value = "test_connection_id"
            
            with patch.object(SMARTAuthProvider, 'initiate_auth_flow') as mock_auth_flow:
                mock_auth_flow.return_value = {
                    "authorization_url": "https://example.com/auth",
                    "state": "test_connection_id"
                }
                
                result = await connection_service.initiate_connection(
                    test_user,
                    "smart_fhir",
                    "https://fhir.example.com",
                    "test_client_id",
                    scope="patient/*.read"
                )
        
        assert result["connection_id"] == "test_connection_id"
        assert result["authorization_url"] == "https://example.com/auth"
        assert "smart_fhir" in connection_service._auth_providers
        mock_connection_repo.create_connection.assert_called_once()
    
    async def test_complete_connection_success(self, connection_service, mock_connection_repo):
        """Test successful connection completion."""
        # Setup mock connection
        mock_connection = UserEHRConnection(
            connection_id="test_connection_id",
            user_id="test_user_123",
            provider_type="smart_fhir",
            fhir_server_url="https://fhir.example.com",
            client_id="test_client_id",
            credentials={},
            is_active=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        
        mock_connection_repo.get_connection_by_id.return_value = mock_connection
        mock_connection_repo.update_connection.return_value = mock_connection
        
        # Setup auth provider
        mock_auth_provider = AsyncMock()
        mock_auth_provider.complete_auth_flow.return_value = {
            "access_token": "test_access_token",
            "refresh_token": "test_refresh_token",
            "expires_in": 3600,
            "patient": "patient123"
        }
        connection_service._auth_providers["smart_fhir"] = mock_auth_provider
        
        result = await connection_service.complete_connection("test_connection_id", "auth_code")
        
        assert result.connection_id == "test_connection_id"
        assert result.is_active is True
        mock_auth_provider.complete_auth_flow.assert_called_once_with("auth_code")
        mock_connection_repo.update_connection.assert_called_once()
    
    async def test_create_fhir_repository_success(self, connection_service, mock_connection_repo):
        """Test successful FHIR repository creation."""
        # Setup mock connection with credentials
        mock_connection = UserEHRConnection(
            connection_id="test_connection_id",
            user_id="test_user_123",
            provider_type="smart_fhir",
            fhir_server_url="https://fhir.example.com",
            client_id="test_client_id",
            credentials={"access_token": "test_token"},
            access_token="test_token",
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        
        mock_connection_repo.get_active_connection_by_user.return_value = mock_connection
        
        # Mock SMARTFHIRRepository
        with patch('optimed.adapters.smart_fhir.repository.SMARTFHIRRepository') as mock_repo_class:
            mock_repo_instance = AsyncMock()
            mock_repo_class.from_connection.return_value = mock_repo_instance
            
            result = await connection_service.create_fhir_repository("test_user_123", "smart_fhir")
        
        assert result is not None
        assert connection_service._active_repositories["test_connection_id"] == mock_repo_instance
        mock_repo_class.from_connection.assert_called_once()
    
    async def test_create_fhir_repository_no_connection(self, connection_service, mock_connection_repo):
        """Test FHIR repository creation with no active connection."""
        mock_connection_repo.get_active_connection_by_user.return_value = None
        
        result = await connection_service.create_fhir_repository("test_user_123", "smart_fhir")
        
        assert result is None