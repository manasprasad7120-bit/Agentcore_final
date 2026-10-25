# Path: src/backend/base/agentcore/services/teams/graph_api.py
"""Microsoft Graph API client for Teams app catalog operations.

Uses delegated OAuth tokens (Authorization Code flow) because
POST /appCatalogs/teamsApps does not support application permissions.
See: https://learn.microsoft.com/en-us/graph/api/teamsapp-publish
"""

from __future__ import annotations

import json
import time

import httpx
from loguru import logger

from agentcore.services.permissions import (
    ConnectorPermissionError,
    parse_oauth_scopes,
    require_scope,
)


class TeamsGraphAPIClient:
    """Client for Microsoft Graph API Teams app catalog operations.

    Uses delegated tokens obtained via OAuth Authorization Code flow.
    Requires ``AppCatalog.ReadWrite.All`` delegated permission for publishing
    flows; bot messaging is independent and does not call Graph at all.

    Modular permissions:
        We request the special ``.default`` scope so Azure AD returns whatever
        the app reg has been admin-consented for, instead of failing with
        AADSTS65001 when AppCatalog.ReadWrite.All has not been granted. The
        actually-granted scopes are read from the token response and stored
        on the client; ``upload_app_to_catalog`` and other write methods then
        gate themselves via :func:`require_scope`.
    """

    GRAPH_BASE = "https://graph.microsoft.com/v1.0"
    TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    AUTHORIZE_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"
    SCOPES = "https://graph.microsoft.com/.default offline_access"

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        access_token: str | None = None,
        refresh_token: str | None = None,
        token_expires_at: float | None = None,
        granted_scopes: list[str] | None = None,
    ):
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._token_expires_at = token_expires_at or 0.0
        # Granted delegated scopes from the token response; empty list = legacy
        # / unknown → require_scope() falls back to permissive (treat all as
        # granted) for backwards compatibility with tokens stored before this
        # field was tracked.
        self._granted_scopes: list[str] = list(granted_scopes) if granted_scopes else []

    def get_authorize_url(self, redirect_uri: str, state: str) -> str:
        """Generate the Microsoft OAuth authorization URL."""
        base = self.AUTHORIZE_URL.format(tenant_id=self._tenant_id)
        params = {
            "client_id": self._client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": self.SCOPES,
            "state": state,
            "response_mode": "query",
            "prompt": "select_account",
        }
        qs = "&".join(f"{k}={httpx.URL('', params={k: v}).params[k]}" for k, v in params.items())
        return f"{base}?{qs}"

    async def exchange_code_for_tokens(self, code: str, redirect_uri: str) -> dict:
        """Exchange an authorization code for access + refresh tokens.

        Returns dict with: access_token, refresh_token, expires_in, token_type
        """
        token_url = self.TOKEN_URL.format(tenant_id=self._tenant_id)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                    "scope": self.SCOPES,
                },
            )
            if response.status_code != 200:
                body = response.text
                logger.error(f"Token exchange failed ({response.status_code}): {body}")
                response.raise_for_status()

            data = response.json()
            self._access_token = data["access_token"]
            self._refresh_token = data.get("refresh_token")
            self._token_expires_at = time.time() + data.get("expires_in", 3600)
            granted = parse_oauth_scopes(data.get("scope"))
            if granted:
                self._granted_scopes = granted

            logger.info(
                f"Successfully exchanged authorization code for tokens "
                f"(granted_scopes={self._granted_scopes or '<none returned>'})"
            )
            return data

    async def _refresh_access_token(self) -> str:
        """Refresh the access token using the stored refresh token."""
        if not self._refresh_token:
            msg = "No refresh token available. User must re-authenticate."
            raise ValueError(msg)

        token_url = self.TOKEN_URL.format(tenant_id=self._tenant_id)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                    "scope": self.SCOPES,
                },
            )
            if response.status_code != 200:
                body = response.text
                logger.error(f"Token refresh failed ({response.status_code}): {body}")
                response.raise_for_status()

            data = response.json()
            self._access_token = data["access_token"]
            if "refresh_token" in data:
                self._refresh_token = data["refresh_token"]
            self._token_expires_at = time.time() + data.get("expires_in", 3600)
            granted = parse_oauth_scopes(data.get("scope"))
            if granted:
                self._granted_scopes = granted

            logger.info("Successfully refreshed access token")
            return self._access_token

    async def _get_access_token(self) -> str:
        """Get a valid access token, refreshing if expired."""
        if not self._access_token:
            msg = "No access token available. User must connect their Microsoft account first."
            raise ValueError(msg)

        # Refresh if expired (with 60s buffer)
        if time.time() >= (self._token_expires_at - 60):
            return await self._refresh_access_token()

        return self._access_token

    async def _get_headers(self) -> dict:
        """Get authorization headers for Graph API requests."""
        token = await self._get_access_token()
        return {
            "Authorization": f"Bearer {token}",
        }

    @property
    def has_tokens(self) -> bool:
        """Check if the client has any tokens (access or refresh)."""
        return bool(self._access_token or self._refresh_token)

    def get_token_data(self) -> dict:
        """Get current token data for storage.

        Includes ``granted_scopes`` so the caller (TeamsService) can persist
        it alongside the token in Redis and consult it later for permission
        gating without re-decoding tokens.
        """
        return {
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "expires_at": self._token_expires_at,
            "granted_scopes": list(self._granted_scopes),
        }

    @property
    def granted_scopes(self) -> list[str]:
        """Granted delegated scopes from the most recent token response.

        Empty list = unknown/legacy → callers using ``require_scope`` /
        ``has_scope`` get the permissive fallback (all permissions treated as
        granted) so existing connections keep working unchanged.
        """
        return list(self._granted_scopes)

    async def upload_app_to_catalog(self, zip_package: bytes) -> str:
        """Upload a Teams app package to the organization app catalog.

        POST /appCatalogs/teamsApps
        Content-Type: application/zip

        Returns: The external teams app ID assigned by Microsoft.

        Raises:
            ConnectorPermissionError: when the connected user's token does not
                include ``AppCatalog.ReadWrite.All`` (admin not consented or
                user not in the right role). API layer translates this to 403.
        """
        require_scope(self._granted_scopes, "AppCatalog.ReadWrite.All")
        headers = await self._get_headers()
        headers["Content-Type"] = "application/zip"

        url = f"{self.GRAPH_BASE}/appCatalogs/teamsApps"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=headers,
                content=zip_package,
                timeout=60.0,
            )

            if response.status_code == 409:
                msg = "An app with this manifest ID already exists in the catalog"
                raise ValueError(msg)

            if response.status_code >= 400:
                body = response.text
                logger.error(f"Graph API upload failed ({response.status_code}): {body}")
                response.raise_for_status()

            data = response.json()
            external_id = data.get("id")

            logger.info(f"Uploaded Teams app to catalog: {external_id}")
            return external_id

    async def update_app_in_catalog(self, teams_app_external_id: str, zip_package: bytes) -> bool:
        """Update an existing app in the catalog.

        POST /appCatalogs/teamsApps/{teamsAppId}/appDefinitions
        Content-Type: application/zip

        Raises:
            ConnectorPermissionError: when ``AppCatalog.ReadWrite.All`` is not
                in the user's granted scopes.
        """
        require_scope(self._granted_scopes, "AppCatalog.ReadWrite.All")
        headers = await self._get_headers()
        headers["Content-Type"] = "application/zip"

        url = f"{self.GRAPH_BASE}/appCatalogs/teamsApps/{teams_app_external_id}/appDefinitions"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=headers,
                content=zip_package,
                timeout=60.0,
            )
            if response.status_code >= 400:
                body = response.text
                logger.error(f"Graph API update failed ({response.status_code}): {body}")
                response.raise_for_status()

            logger.info(f"Updated Teams app in catalog: {teams_app_external_id}")
            return True

    async def delete_app_from_catalog(self, teams_app_external_id: str) -> bool:
        """Remove an app from the catalog.

        DELETE /appCatalogs/teamsApps/{teamsAppId}

        Raises:
            ConnectorPermissionError: when ``AppCatalog.ReadWrite.All`` is not
                in the user's granted scopes.
        """
        require_scope(self._granted_scopes, "AppCatalog.ReadWrite.All")
        headers = await self._get_headers()

        url = f"{self.GRAPH_BASE}/appCatalogs/teamsApps/{teams_app_external_id}"

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                url,
                headers=headers,
                timeout=30.0,
            )

            if response.status_code == 404:
                logger.warning(f"Teams app {teams_app_external_id} not found in catalog (already deleted?)")
                return True

            if response.status_code >= 400:
                body = response.text
                logger.error(f"Graph API delete failed ({response.status_code}): {body}")
                response.raise_for_status()

            logger.info(f"Deleted Teams app from catalog: {teams_app_external_id}")
            return True

    async def get_app_status(self, teams_app_external_id: str) -> dict | None:
        """Get the current status of an app in the catalog.

        GET /appCatalogs/teamsApps/{teamsAppId}
        """
        headers = await self._get_headers()

        url = f"{self.GRAPH_BASE}/appCatalogs/teamsApps/{teams_app_external_id}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=headers,
                timeout=30.0,
            )

            if response.status_code == 404:
                return None

            if response.status_code >= 400:
                body = response.text
                logger.error(f"Graph API status check failed ({response.status_code}): {body}")
                response.raise_for_status()

            return response.json()

    async def find_app_by_manifest_id(self, manifest_id: str) -> str | None:
        """Find a Teams app in the catalog by its manifest ID (externalId).

        GET /appCatalogs/teamsApps?$filter=externalId eq '{manifest_id}'

        Returns: The Microsoft-assigned app ID, or None if not found.
        """
        headers = await self._get_headers()

        url = f"{self.GRAPH_BASE}/appCatalogs/teamsApps"
        params = {"$filter": f"externalId eq '{manifest_id}'"}

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=headers,
                params=params,
                timeout=30.0,
            )

            if response.status_code >= 400:
                body = response.text
                logger.error(f"Graph API search failed ({response.status_code}): {body}")
                return None

            data = response.json()
            apps = data.get("value", [])
            if apps:
                app_id = apps[0].get("id")
                logger.info(f"Found existing Teams app by manifest ID {manifest_id}: {app_id}")
                return app_id

            return None

    def invalidate_token(self) -> None:
        """Force token refresh on next request."""
        self._access_token = None
        self._token_expires_at = 0.0
