"""
SITHS NetID Enterprise Authentication Provider

This module implements authentication using GrandID's NetID Enterprise API
for SITHS card-based authentication.

API Documentation: https://docs.grandid.com/
"""

from __future__ import annotations
import os
import httpx
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from optimed.core.logging_utils import get_logger

logger = get_logger(__name__)


class SITHSAuthException(Exception):
    """Exception raised for SITHS authentication errors."""
    pass


class SITHSAuthProvider:
    """
    SITHS authentication provider using GrandID NetID Enterprise API.

    Environment variables required:
        GRANDID_API_KEY: API key for GrandID
        GRANDID_SERVICE_KEY: Service key for SITHS NetID Enterprise
        GRANDID_BASE_URL: Base URL for GrandID API (test or production)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        service_key: Optional[str] = None,
        base_url: Optional[str] = None
    ):
        self.api_key = api_key or os.getenv('GRANDID_API_KEY')
        self.service_key = service_key or os.getenv('GRANDID_SERVICE_KEY')
        base_url_value = base_url or os.getenv('GRANDID_BASE_URL', 'https://client-test.grandid.com')
        self.base_url = base_url_value.rstrip('/') if base_url_value else 'https://client-test.grandid.com'

        if not self.api_key:
            raise ValueError("GRANDID_API_KEY not set")
        if not self.service_key:
            raise ValueError("GRANDID_SERVICE_KEY not set")

    async def initiate_siths_auth(self, callback_url: str) -> Dict[str, Any]:
        """
        Initiate SITHS authentication flow using GrandID FederatedLogin.

        Args:
            callback_url: URL where GrandID will redirect after authentication

        Returns:
            Dict containing:
                - redirectUrl: URL to redirect user to for authentication
                - sessionid: Session ID for later GetSession call (if provided)

        Raises:
            SITHSAuthException: If authentication initiation fails
        """
        try:
            # Type narrowing: api_key and service_key are guaranteed to be str at this point
            assert self.api_key is not None
            assert self.service_key is not None

            logger.info("=" * 80)
            logger.info("[SITHS DEBUG] Initiating SITHS authentication")
            logger.info(f"[SITHS DEBUG] Base URL: {self.base_url}")
            logger.info(f"[SITHS DEBUG] API Key: {self.api_key[:10]}... (masked)")
            logger.info(f"[SITHS DEBUG] Service Key: {self.service_key[:10]}... (masked)")
            logger.info(f"[SITHS DEBUG] Callback URL: {callback_url}")

            async with httpx.AsyncClient() as client:
                # GrandID FederatedLogin API call
                # GET request with query parameters
                full_url = f"{self.base_url}/json1.1/FederatedLogin"
                params = {
                    "apiKey": self.api_key,
                    "authenticateServiceKey": self.service_key,
                    "callbackUrl": callback_url
                }

                logger.info(f"[SITHS DEBUG] Making GET request to: {full_url}")
                logger.info(f"[SITHS DEBUG] Request params: apiKey={params['apiKey'][:10]}..., authenticateServiceKey={params['authenticateServiceKey'][:10]}..., callbackUrl={params['callbackUrl']}")

                response = await client.get(
                    full_url,
                    params=params,
                    timeout=30.0
                )

                logger.info(f"[SITHS DEBUG] Response status code: {response.status_code}")
                logger.info(f"[SITHS DEBUG] Response headers: {dict(response.headers)}")
                logger.info(f"[SITHS DEBUG] Response body: {response.text}")

                response.raise_for_status()
                data = response.json()

                logger.info(f"[SITHS DEBUG] Parsed response data: {data}")
                logger.info(f"[SITHS DEBUG] Redirect URL: {data.get('redirectUrl')}")

                # GrandID returns 'sessionId' with capital I
                session_id = data.get("sessionId") or data.get("sessionid")
                logger.info(f"[SITHS DEBUG] Session ID: {session_id}")
                logger.info("=" * 80)

                return {
                    "redirectUrl": data.get("redirectUrl"),
                    "sessionid": session_id
                }

        except httpx.HTTPError as e:
            logger.error(f"[SITHS ERROR] HTTP Error during initiation: {str(e)}")
            # HTTPError may or may not have a response attribute
            response = getattr(e, 'response', None)
            if response is not None:
                logger.error(f"[SITHS ERROR] Response status: {response.status_code}")
                logger.error(f"[SITHS ERROR] Response body: {response.text}")
            else:
                logger.error("[SITHS ERROR] No response available")
            raise SITHSAuthException(f"Failed to initiate SITHS authentication: {str(e)}")
        except Exception as e:
            logger.error(f"[SITHS ERROR] Unexpected error during SITHS authentication: {str(e)}")
            import traceback
            logger.error(f"[SITHS ERROR] Traceback: {traceback.format_exc()}")
            raise SITHSAuthException(f"Unexpected error: {str(e)}")

    async def get_session_data(self, sessionid: str) -> Dict[str, Any]:
        """
        Get authenticated user data using GrandID GetSession.

        Args:
            sessionid: The sessionid from callback (grandidsession parameter)

        Returns:
            Dict containing user attributes from SITHS certificate

        Raises:
            SITHSAuthException: If GetSession fails
        """
        try:
            # Type narrowing: api_key and service_key are guaranteed to be str at this point
            assert self.api_key is not None
            assert self.service_key is not None

            logger.info("=" * 80)
            logger.info(f"[SITHS DEBUG] Getting session data for sessionid: {sessionid}")

            async with httpx.AsyncClient() as client:
                # GrandID GetSession API call
                # GET request with query parameters
                full_url = f"{self.base_url}/json1.1/GetSession"
                params = {
                    "apiKey": self.api_key,
                    "authenticateServiceKey": self.service_key,
                    "sessionid": sessionid
                }

                logger.info(f"[SITHS DEBUG] Making GET request to: {full_url}")
                logger.info(f"[SITHS DEBUG] Request params: apiKey={params['apiKey'][:10]}..., authenticateServiceKey={params['authenticateServiceKey'][:10]}..., sessionid={sessionid}")

                response = await client.get(
                    full_url,
                    params=params,
                    timeout=30.0
                )

                logger.info(f"[SITHS DEBUG] GetSession response status: {response.status_code}")
                logger.info(f"[SITHS DEBUG] GetSession response headers: {dict(response.headers)}")
                logger.info(f"[SITHS DEBUG] GetSession response body: {response.text}")

                response.raise_for_status()
                data = response.json()

                logger.info(f"[SITHS DEBUG] GetSession parsed data: {data}")

                user_info = self._extract_user_info(data)
                logger.info(f"[SITHS DEBUG] Extracted user info: {user_info}")
                logger.info("=" * 80)

                return user_info

        except httpx.HTTPError as e:
            logger.error(f"[SITHS ERROR] HTTP Error getting session data: {str(e)}")
            # HTTPError may or may not have a response attribute
            response = getattr(e, 'response', None)
            if response is not None:
                logger.error(f"[SITHS ERROR] Response status: {response.status_code}")
                logger.error(f"[SITHS ERROR] Response body: {response.text}")
            else:
                logger.error("[SITHS ERROR] No response available")
            raise SITHSAuthException(f"Failed to get session data: {str(e)}")
        except Exception as e:
            logger.error(f"[SITHS ERROR] Unexpected error getting SITHS session: {str(e)}")
            import traceback
            logger.error(f"[SITHS ERROR] Traceback: {traceback.format_exc()}")
            raise SITHSAuthException(f"Unexpected error: {str(e)}")

    def _extract_user_info(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract user information from SITHS certificate data.

        Args:
            session_data: Response data from GrandID GetSession

        Returns:
            Dict containing:
                - hsa_id: HSA ID from certificate
                - given_name: First name
                - surname: Last name
                - email: Email address (if available)
                - organization: Organization name (if available)
                - organizational_unit: Department/unit (if available)
                - client_certification_serial: Certificate serial number
        """
        # GrandID returns user attributes in the response
        # The exact structure may vary - adjust based on actual response
        user_attributes = session_data.get("userAttributes", session_data)

        # Extract HSA ID - typically found in certificate subject
        # Format varies, could be in CN, serialNumber, or custom field
        hsa_id = user_attributes.get("serialNumber")

        logger.info(f"[SITHS AUTH] HSA ID: {hsa_id}")

        # Try to extract organizational information (may not be present)
        # Common field names: organizationalUnit, OU, organization, ou
        org_unit = (
            user_attributes.get("organizationalUnit") or
            user_attributes.get("OU") or
            user_attributes.get("ou") or
            ""
        )

        organization = (
            user_attributes.get("organization") or
            user_attributes.get("O") or
            user_attributes.get("o") or
            ""
        )

        return {
            "hsa_id": hsa_id,
            "given_name": user_attributes.get("firstname", ""),
            "surname": user_attributes.get("lastname", ""),
            "email": user_attributes.get("DN_email", ""),
            "organizational_unit": org_unit,
            "organization": organization,
            "client_certification_serial": user_attributes.get("clientCertificateSerial", ""),
            "raw_attributes": user_attributes  # Store all attributes for debugging
        }

    async def logout_siths(self, sessionid: str) -> bool:
        """
        Logout SITHS session using GrandID Logout API.

        Args:
            sessionid: The sessionid of the session to logout

        Returns:
            True if logout successful, False otherwise
        """
        try:
            async with httpx.AsyncClient() as client:
                # GrandID Logout API call
                # GET request with query parameters
                response = await client.get(
                    f"{self.base_url}/json1.1/Logout",
                    params={
                        "apiKey": self.api_key,
                        "authenticateServiceKey": self.service_key,
                        "sessionid": sessionid
                    },
                    timeout=30.0
                )

                response.raise_for_status()
                logger.info(f"SITHS session logged out: {sessionid}")
                return True

        except Exception as e:
            logger.error(f"Failed to logout SITHS session: {str(e)}")
            return False

    def extract_hsa_id(self, user_info: Dict[str, Any]) -> Optional[str]:
        """
        Extract and validate HSA ID from user info.

        Args:
            user_info: User info dict from _extract_user_info

        Returns:
            HSA ID string if valid, None otherwise
        """
        hsa_id = user_info.get("hsa_id", "").strip()

        if not hsa_id:
            logger.warning("No HSA ID found in SITHS certificate")
            return None

        # Basic validation (update based on actual HSA ID format requirements)
        # Typical format: SE followed by 12 digits, or just the number
        if hsa_id:
            return hsa_id

        logger.warning(f"Invalid HSA ID format: {hsa_id}")
        return None

    def get_siths_metadata(self, user_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get SITHS metadata for storage in user record.

        Args:
            user_info: User info dict from _extract_user_info

        Returns:
            Dict containing certificate metadata
        """
        return {
            "certificate_serial": user_info.get("client_certification_serial", ""),
            "last_siths_login": datetime.now(timezone.utc).isoformat(),
            "authentication_method": "SITHS NetID Enterprise",
            "raw_attributes": user_info.get("raw_attributes", {})  # Store all attributes for debugging
        }
