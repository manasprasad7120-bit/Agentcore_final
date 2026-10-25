"""
SharePoint Service for backend token validation and file operations.

Uses user-delegated OAuth 2.0 authorization code flow for the orchestrator
file picker. The user authenticates via a Microsoft popup, and the backend
exchanges the auth code for an access token to browse / download files.

Credentials are read from environment variables populated at startup from
Azure Key Vault — no secrets are hardcoded.
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

# Read from environment (populated by Key Vault at startup).
# The orchestrator SharePoint file picker uses its own dedicated credentials
# (SHAREPOINT_TENANT_ID / SHAREPOINT_CLIENT_ID / SHAREPOINT_CLIENT_SECRET),
# kept separate from the main agentcore login (AZURE_*). If the SHAREPOINT_*
# vars are not set, we fall back to AZURE_* for backward compatibility.
SHAREPOINT_TENANT_ID = os.getenv("SHAREPOINT_TENANT_ID", "") or os.getenv("AZURE_TENANT_ID", "")
SHAREPOINT_CLIENT_ID = os.getenv("SHAREPOINT_CLIENT_ID", "") or os.getenv("AZURE_CLIENT_ID", "")
SHAREPOINT_CLIENT_SECRET = os.getenv("SHAREPOINT_CLIENT_SECRET", "") or os.getenv("AZURE_CLIENT_SECRET", "")


class SharePointService:
    """Service for SharePoint/OneDrive operations via Microsoft Graph API"""

    GRAPH_API_ENDPOINT = "https://graph.microsoft.com/v1.0"
    TOKEN_ENDPOINT = f"https://login.microsoftonline.com/{SHAREPOINT_TENANT_ID}/oauth2/v2.0/token"
    AUTHORIZE_ENDPOINT = f"https://login.microsoftonline.com/{SHAREPOINT_TENANT_ID}/oauth2/v2.0/authorize"

    USER_SCOPES = "User.Read Files.Read.All Sites.Read.All"

    @staticmethod
    def _get_credentials() -> tuple[str, str, str]:
        """Get credentials, re-reading from env in case they were loaded after import.

        Prefers the dedicated SHAREPOINT_* vars (used by the orchestrator file
        picker) and falls back to AZURE_* for older deployments.
        """
        tenant_id = (
            os.getenv("SHAREPOINT_TENANT_ID", "")
            or os.getenv("AZURE_TENANT_ID", "")
            or SHAREPOINT_TENANT_ID
        )
        client_id = (
            os.getenv("SHAREPOINT_CLIENT_ID", "")
            or os.getenv("AZURE_CLIENT_ID", "")
            or SHAREPOINT_CLIENT_ID
        )
        client_secret = (
            os.getenv("SHAREPOINT_CLIENT_SECRET", "")
            or os.getenv("AZURE_CLIENT_SECRET", "")
            or SHAREPOINT_CLIENT_SECRET
        )
        return tenant_id, client_id, client_secret

    @staticmethod
    def _get_token_endpoint() -> str:
        tenant_id, _, _ = SharePointService._get_credentials()
        return f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

    @staticmethod
    def _get_authorize_endpoint() -> str:
        tenant_id, _, _ = SharePointService._get_credentials()
        return f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"

    # ── OAuth ────────────────────────────────────────────────────────

    @staticmethod
    def build_auth_url(redirect_uri: str, state: str = "") -> str:
        """Build the Microsoft OAuth authorization URL for the popup."""
        _, client_id, _ = SharePointService._get_credentials()
        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": SharePointService.USER_SCOPES,
            "response_mode": "query",
            "prompt": "select_account",
        }
        if state:
            params["state"] = state
        return f"{SharePointService._get_authorize_endpoint()}?{urlencode(params)}"

    @staticmethod
    def validate_access_token(access_token: str) -> Optional[Dict[str, Any]]:
        """
        Validate an access token by calling Microsoft Graph API.
        Returns user info if valid, None otherwise.
        """
        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }

            response = requests.get(
                f"{SharePointService.GRAPH_API_ENDPOINT}/me",
                headers=headers,
                timeout=10,
            )

            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Token validation failed: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error validating token: {e}")
            return None

    @staticmethod
    def exchange_code_for_token(auth_code: str, redirect_uri: str) -> Optional[Dict[str, Any]]:
        """
        Exchange authorization code for access token (backend OAuth flow).
        """
        try:
            _, client_id, client_secret = SharePointService._get_credentials()

            data = {
                "client_id": client_id,
                "client_secret": client_secret,
                "code": auth_code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "scope": "User.Read Files.Read.All Sites.Read.All",
            }

            response = requests.post(
                SharePointService._get_token_endpoint(),
                data=data,
                timeout=10,
            )

            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Token exchange failed: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Error exchanging code for token: {e}")
            return None

    @staticmethod
    def get_on_behalf_of_token(user_access_token: str) -> Optional[str]:
        """
        Get an on-behalf-of token for backend operations.
        This allows the backend to act on behalf of the user.
        """
        try:
            _, client_id, client_secret = SharePointService._get_credentials()

            data = {
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": user_access_token,
                "requested_token_use": "on_behalf_of",
                "scope": "https://graph.microsoft.com/.default",
            }

            response = requests.post(
                SharePointService._get_token_endpoint(),
                data=data,
                timeout=10,
            )

            if response.status_code == 200:
                return response.json().get("access_token")
            else:
                logger.error(f"OBO token request failed: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error getting OBO token: {e}")
            return None

    # ── File operations ──────────────────────────────────────────────

    @staticmethod
    def get_file_content(access_token: str, file_id: str) -> Optional[bytes]:
        """
        Download file content from SharePoint/OneDrive using file ID.
        """
        try:
            headers = {"Authorization": f"Bearer {access_token}"}

            response = requests.get(
                f"{SharePointService.GRAPH_API_ENDPOINT}/me/drive/items/{file_id}/content",
                headers=headers,
                timeout=30,
            )

            if response.status_code == 200:
                return response.content
            else:
                logger.error(f"Failed to download file: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            return None

    @staticmethod
    def get_drive_file_content(
        access_token: str, drive_id: str, file_id: str,
    ) -> Optional[bytes]:
        """
        Download file content from a specific SharePoint drive.
        """
        try:
            headers = {"Authorization": f"Bearer {access_token}"}

            response = requests.get(
                f"{SharePointService.GRAPH_API_ENDPOINT}/drives/{drive_id}/items/{file_id}/content",
                headers=headers,
                timeout=30,
            )

            if response.status_code == 200:
                return response.content
            else:
                logger.error(f"Failed to download drive file: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error downloading drive file: {e}")
            return None

    @staticmethod
    def resolve_sharepoint_url(
        access_token: str, sharing_url: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Resolve a SharePoint sharing URL to a DriveItem.
        """
        try:
            # Encode URL to base64 and remove padding, then prefix with u!
            sharing_url_bytes = sharing_url.encode("utf-8")
            base64_url = base64.b64encode(sharing_url_bytes).decode("utf-8")
            share_id = "u!" + base64_url.rstrip("=").replace("/", "_").replace("+", "-")

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }

            response = requests.get(
                f"{SharePointService.GRAPH_API_ENDPOINT}/shares/{share_id}/driveItem",
                headers=headers,
                timeout=20,
            )

            if response.status_code == 200:
                return response.json()
            else:
                logger.error(
                    f"Failed to resolve share link: {response.status_code} - {response.text}"
                )
                return None

        except Exception as e:
            logger.error(f"Error resolving share link: {e}")
            return None

    # ── Browse operations (for file picker) ──────────────────────────

    @staticmethod
    def list_root_files(
        access_token: str, top: int = 50,
    ) -> Optional[list[Dict[str, Any]]]:
        """List files at the root of the user's OneDrive."""
        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }

            response = requests.get(
                f"{SharePointService.GRAPH_API_ENDPOINT}/me/drive/root/children",
                headers=headers,
                params={
                    "$top": str(top),
                    "$select": "id,name,size,lastModifiedDateTime,file,folder,webUrl",
                },
                timeout=15,
            )

            if response.status_code == 200:
                return response.json().get("value", [])
            else:
                logger.error(f"Failed to list root files: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error listing root files: {e}")
            return None

    @staticmethod
    def list_folder(
        access_token: str, folder_id: str, top: int = 50,
    ) -> Optional[list[Dict[str, Any]]]:
        """List files inside a folder by item ID."""
        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }

            response = requests.get(
                f"{SharePointService.GRAPH_API_ENDPOINT}/me/drive/items/{folder_id}/children",
                headers=headers,
                params={
                    "$top": str(top),
                    "$select": "id,name,size,lastModifiedDateTime,file,folder,webUrl",
                },
                timeout=15,
            )

            if response.status_code == 200:
                return response.json().get("value", [])
            else:
                logger.error(f"Failed to list folder: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error listing folder: {e}")
            return None

    @staticmethod
    def list_sharepoint_sites(
        access_token: str,
    ) -> Optional[list[Dict[str, Any]]]:
        """List SharePoint sites the user has access to."""
        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }

            response = requests.get(
                f"{SharePointService.GRAPH_API_ENDPOINT}/sites",
                headers=headers,
                params={"search": "*", "$top": "50"},
                timeout=15,
            )

            if response.status_code == 200:
                return response.json().get("value", [])
            else:
                logger.error(f"Failed to list sites: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error listing sites: {e}")
            return None

    @staticmethod
    def list_site_drives(
        access_token: str, site_id: str,
    ) -> Optional[list[Dict[str, Any]]]:
        """List document libraries for a SharePoint site."""
        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }

            response = requests.get(
                f"{SharePointService.GRAPH_API_ENDPOINT}/sites/{site_id}/drives",
                headers=headers,
                timeout=15,
            )

            if response.status_code == 200:
                return response.json().get("value", [])
            else:
                logger.error(f"Failed to list site drives: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error listing site drives: {e}")
            return None

    @staticmethod
    def list_drive_items(
        access_token: str, drive_id: str, folder_id: str = "", top: int = 50,
    ) -> Optional[list[Dict[str, Any]]]:
        """List items in a SharePoint drive (optionally inside a folder)."""
        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }

            if folder_id:
                url = f"{SharePointService.GRAPH_API_ENDPOINT}/drives/{drive_id}/items/{folder_id}/children"
            else:
                url = f"{SharePointService.GRAPH_API_ENDPOINT}/drives/{drive_id}/root/children"

            response = requests.get(
                url,
                headers=headers,
                params={
                    "$top": str(top),
                    "$select": "id,name,size,lastModifiedDateTime,file,folder,webUrl",
                },
                timeout=15,
            )

            if response.status_code == 200:
                return response.json().get("value", [])
            else:
                logger.error(f"Failed to list drive items: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error listing drive items: {e}")
            return None

    @staticmethod
    def search_files(
        access_token: str, query: str, top: int = 25,
    ) -> Optional[list[Dict[str, Any]]]:
        """Search across the user's OneDrive."""
        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }

            safe_query = query.replace("'", "''")
            response = requests.get(
                f"{SharePointService.GRAPH_API_ENDPOINT}/me/drive/root/search(q='{safe_query}')",
                headers=headers,
                params={
                    "$top": str(top),
                    "$select": "id,name,size,lastModifiedDateTime,file,folder,webUrl",
                },
                timeout=15,
            )

            if response.status_code == 200:
                return response.json().get("value", [])
            else:
                logger.error(f"Failed to search files: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error searching files: {e}")
            return None
