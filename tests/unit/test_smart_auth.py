import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from optimed.adapters.smart_fhir.auth_provider import SMARTAuthProvider

class TestSMARTAuthProvider:
    """Unit tests for SMARTAuthProvider."""
    
    @pytest.fixture
    def auth_provider(self):
        return SMARTAuthProvider(
            fhir_server_url="https://test-fhir.example.com",
            client_id="test_client_id",
            client_secret="test_client_secret",
            redirect_uri="http://localhost:3000/api/smart/callback"
        )
    
    def test_init(self, auth_provider):
        """Test SMARTAuthProvider initialization."""
        assert auth_provider._base == "https://test-fhir.example.com"
        assert auth_provider._client_id == "test_client_id"
        assert auth_provider._client_secret == "test_client_secret"
        assert auth_provider._redirect_uri == "http://localhost:3000/api/smart/callback"
        assert auth_provider._token_url == "https://test-fhir.example.com/token"
    
    async def test_initiate_auth_flow_basic(self, auth_provider):
        """Test basic auth flow initiation."""
        result = await auth_provider.initiate_auth_flow(state="test_state")
        
        assert result["provider_type"] == "smart_fhir"
        assert result["state"] == "test_state"
        assert "authorization_url" in result
        
        # Check URL components
        auth_url = result["authorization_url"]
        assert "https://test-fhir.example.com/authorize" in auth_url
        assert "response_type=code" in auth_url
        assert "client_id=test_client_id" in auth_url
        assert "state=test_state" in auth_url
        assert "scope=patient%2F%2A.read" in auth_url  # URL encoded
    
    async def test_initiate_auth_flow_custom_scope(self, auth_provider):
        """Test auth flow initiation with custom scope."""
        result = await auth_provider.initiate_auth_flow(
            state="test_state",
            scope="patient/*.read user/*.read"
        )
        
        auth_url = result["authorization_url"]
        assert "scope=patient%2F%2A.read+user%2F%2A.read" in auth_url or "scope=patient/*.read user/*.read" in auth_url
    
    @patch('httpx.AsyncClient')
    async def test_complete_auth_flow_success(self, mock_async_client, auth_provider):
        """Test successful auth flow completion."""
        # Mock the HTTP response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "test_access_token",
            "refresh_token": "test_refresh_token",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": "patient/*.read",
            "patient": "patient123"
        }
        mock_response.raise_for_status.return_value = None
        
        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_async_client.return_value.__aenter__.return_value = mock_client_instance
        
        result = await auth_provider.complete_auth_flow("test_auth_code")
        
        # Verify the result
        assert result["access_token"] == "test_access_token"
        assert result["refresh_token"] == "test_refresh_token"
        assert result["expires_in"] == 3600
        assert result["token_type"] == "Bearer"
        assert result["scope"] == "patient/*.read"
        assert result["patient"] == "patient123"
        
        # Verify the HTTP call
        mock_client_instance.post.assert_called_once()
        call_args = mock_client_instance.post.call_args
        assert call_args[0][0] == "https://test-fhir.example.com/token"
        
        posted_data = call_args[1]["data"]
        assert posted_data["grant_type"] == "authorization_code"
        assert posted_data["code"] == "test_auth_code"
        assert posted_data["client_id"] == "test_client_id"
        assert posted_data["client_secret"] == "test_client_secret"
    
    @patch('httpx.AsyncClient')
    async def test_complete_auth_flow_http_error(self, mock_async_client, auth_provider):
        """Test auth flow completion with HTTP error."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad request", request=MagicMock(), response=MagicMock()
        )
        
        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_async_client.return_value.__aenter__.return_value = mock_client_instance
        
        with pytest.raises(httpx.HTTPStatusError):
            await auth_provider.complete_auth_flow("invalid_code")
    
    @patch('httpx.AsyncClient')
    async def test_refresh_token_success(self, mock_async_client, auth_provider):
        """Test successful token refresh."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 3600,
            "token_type": "Bearer"
        }
        mock_response.raise_for_status.return_value = None
        
        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_async_client.return_value.__aenter__.return_value = mock_client_instance
        
        result = await auth_provider.refresh_token("old_refresh_token")
        
        assert result["access_token"] == "new_access_token"
        assert result["refresh_token"] == "new_refresh_token"
        
        # Verify the HTTP call
        posted_data = mock_client_instance.post.call_args[1]["data"]
        assert posted_data["grant_type"] == "refresh_token"
        assert posted_data["refresh_token"] == "old_refresh_token"
    
    @patch('httpx.AsyncClient')
    async def test_validate_token_valid(self, mock_async_client, auth_provider):
        """Test token validation with valid token."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        
        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = mock_response
        mock_async_client.return_value.__aenter__.return_value = mock_client_instance
        
        result = await auth_provider.validate_token("valid_token")
        
        assert result["valid"] is True
        mock_client_instance.get.assert_called_once_with(
            "https://test-fhir.example.com/metadata",
            headers={"Authorization": "Bearer valid_token"}
        )
    
    @patch('httpx.AsyncClient')
    async def test_validate_token_invalid(self, mock_async_client, auth_provider):
        """Test token validation with invalid token."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        
        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = mock_response
        mock_async_client.return_value.__aenter__.return_value = mock_client_instance
        
        result = await auth_provider.validate_token("invalid_token")
        
        assert result["valid"] is False
    
    @patch('httpx.AsyncClient')
    async def test_validate_token_network_error(self, mock_async_client, auth_provider):
        """Test token validation with network error."""
        mock_client_instance = AsyncMock()
        mock_client_instance.get.side_effect = Exception("Network error")
        mock_async_client.return_value.__aenter__.return_value = mock_client_instance
        
        result = await auth_provider.validate_token("token")
        
        assert result["valid"] is False