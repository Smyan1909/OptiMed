from __future__ import annotations
from typing import Dict, Any, Optional
from urllib.parse import urlencode
import httpx

from optimed.core.ports import AuthenticationProvider

class SMARTAuthProvider(AuthenticationProvider):
    """SMART on FHIR authentication provider."""
    
    def __init__(
        self,
        fhir_server_url: str,
        client_id: str,
        client_secret: Optional[str] = None,
        redirect_uri: str = "http://localhost:3000/api/smart/callback",
        timeout: float = 10.0
    ):
        self._base = fhir_server_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._timeout = timeout
        self._token_url = f"{self._base}/token"
    
    async def initiate_auth_flow(self, **kwargs: Any) -> Dict[str, Any]:
        """Initiate SMART authorization flow."""
        scope = kwargs.get("scope", "patient/*.read")
        state = kwargs.get("state")
        
        auth_url = f"{self._base}/authorize"
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "scope": scope,
            "aud": self._base        }
        
        if state:
            params["state"] = state
        
        auth_url_with_params = auth_url + "?" + urlencode(params)
        
        return {
            "authorization_url": auth_url_with_params,
            "state": state,
            "provider_type": "smart_fhir"
        }
    
    async def complete_auth_flow(self, auth_code: str, **kwargs: Any) -> Dict[str, Any]:
        """Complete SMART authorization flow."""
        data = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": self._redirect_uri,
            "client_id": self._client_id,
        }
        
        if self._client_secret:
            data["client_secret"] = self._client_secret

        async with httpx.AsyncClient(timeout=self._timeout) as auth_client:
            response = await auth_client.post(self._token_url, data=data)
            response.raise_for_status()
            token_data = response.json()

            return {
                "access_token": token_data["access_token"],
                "refresh_token": token_data.get("refresh_token"),
                "expires_in": token_data.get("expires_in", 3600),
                "token_type": token_data.get("token_type", "Bearer"),
                "scope": token_data.get("scope"),
                "patient": token_data.get("patient")  # SMART-specific patient context
            }
    
    async def refresh_token(self, refresh_token: str, **kwargs: Any) -> Dict[str, Any]:
        """Refresh an expired access token."""
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self._client_id,
        }
        
        if self._client_secret:
            data["client_secret"] = self._client_secret

        async with httpx.AsyncClient(timeout=self._timeout) as auth_client:
            response = await auth_client.post(self._token_url, data=data)
            response.raise_for_status()
            token_data = response.json()

            return {
                "access_token": token_data["access_token"],
                "refresh_token": token_data.get("refresh_token", refresh_token),
                "expires_in": token_data.get("expires_in", 3600),
                "token_type": token_data.get("token_type", "Bearer")
            }
    
    async def validate_token(self, token: str) -> Dict[str, Any]:
        """Validate if an access token is still valid."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{self._base}/metadata",
                    headers={"Authorization": f"Bearer {token}"}
                )
                return {"valid": response.status_code == 200}
        except Exception:
            return {"valid": False}