"""Microsoft Graph Mail client — isolated from Teams Graph module.

Handles OAuth token lifecycle and all Outlook mail operations
(list messages, get message, list attachments, reply, reply-all, send).

Does NOT import from ``services/teams/`` — completely independent.
"""
from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote, urlencode

import httpx
from loguru import logger

from agentcore.services.permissions import (
    ConnectorPermissionError,
    parse_oauth_scopes,
    require_scope,
)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
AUTHORIZE_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"
# ``.default`` lets Azure AD return a token with whatever scopes the app reg
# was admin-consented for, instead of failing with AADSTS65001 when our
# requested list exceeds what's been consented. The granted scopes are then
# read from the token response and stored on the client so write methods can
# self-gate.
MAIL_SCOPES = "https://graph.microsoft.com/.default offline_access"


class OutlookGraphMailClient:
    """Client for Microsoft Graph Mail API operations.

    Instantiate with Azure app credentials and (optionally) a user's
    tokens obtained via the OAuth Authorization Code flow.
    """

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
        # Actually-granted scopes from the OAuth token response. Empty list is
        # treated as a permissive fallback by require_scope() so legacy callers
        # that don't pass this still work as before.
        self._granted_scopes: list[str] = list(granted_scopes) if granted_scopes else []

    # ── OAuth helpers ────────────────────────────────────────

    def get_authorize_url(self, redirect_uri: str, state: str) -> str:
        """Build Microsoft OAuth2 authorize URL for Mail scopes."""
        base = AUTHORIZE_URL.format(tenant_id=self._tenant_id)
        params = urlencode({
            "client_id": self._client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": MAIL_SCOPES,
            "state": state,
            "response_mode": "query",
            "prompt": "select_account",
        })
        return f"{base}?{params}"

    async def exchange_code_for_tokens(self, code: str, redirect_uri: str) -> dict:
        """Exchange authorization code for access + refresh tokens.

        Returns the full token response dict from Microsoft.
        Updates internal token state so subsequent API calls work immediately.
        """
        token_url = TOKEN_URL.format(tenant_id=self._tenant_id)
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                token_url,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                    "scope": MAIL_SCOPES,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token")
        self._token_expires_at = time.time() + data.get("expires_in", 3600)
        granted = parse_oauth_scopes(data.get("scope"))
        if granted:
            self._granted_scopes = granted
        return data

    async def _refresh_access_token(self) -> str:
        """Refresh the access token using the refresh token."""
        if not self._refresh_token:
            msg = "No refresh token. User must re-authenticate."
            raise ValueError(msg)
        token_url = TOKEN_URL.format(tenant_id=self._tenant_id)
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                token_url,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                    "scope": MAIL_SCOPES,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token", self._refresh_token)
        self._token_expires_at = time.time() + data.get("expires_in", 3600)
        granted = parse_oauth_scopes(data.get("scope"))
        if granted:
            self._granted_scopes = granted
        logger.debug("Outlook access token refreshed")
        return self._access_token

    async def _get_valid_token(self) -> str:
        """Get a valid access token, refreshing if within 60 s of expiry."""
        if not self._access_token:
            msg = "No access token. Complete OAuth flow first."
            raise ValueError(msg)
        if time.time() >= (self._token_expires_at - 60):
            return await self._refresh_access_token()
        return self._access_token

    async def _headers(self) -> dict[str, str]:
        token = await self._get_valid_token()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # ── Token state (for saving back to DB after refresh) ────

    def get_token_state(self) -> dict:
        """Return current token state for persisting back to provider_config."""
        return {
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "token_expires_at": self._token_expires_at,
            "granted_scopes": list(self._granted_scopes),
        }

    @property
    def granted_scopes(self) -> list[str]:
        """The actually-granted Mail scopes from the OAuth token response.

        Empty list = unknown/legacy → callers using require_scope/has_scope get
        the permissive fallback (treats all permissions as granted).
        """
        return list(self._granted_scopes)

    # ── Mail read ────────────────────────────────────────────

    async def get_me(self) -> dict:
        """Get the authenticated user's profile."""
        headers = await self._headers()
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{GRAPH_BASE}/me", headers=headers, timeout=10)
            resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _odata_escape(value: str) -> str:
        """Escape single quotes for OData $filter values."""
        return value.replace("'", "''")

    @staticmethod
    def _validate_folder(folder: str) -> str:
        """Validate folder name for use in URL path."""
        if not folder:
            return "inbox"
        if "/" in folder or "\\" in folder or ".." in folder:
            raise ValueError(f"Invalid folder name: {folder}")
        return folder

    async def list_messages(
        self,
        folder: str = "inbox",
        top: int = 10,
        filter_sender: str | None = None,
        filter_subject: str | None = None,
        select: str = "id,subject,from,receivedDateTime,bodyPreview,hasAttachments,body",
    ) -> list[dict]:
        """List messages from a mail folder."""
        headers = await self._headers()
        safe_folder = self._validate_folder(folder)
        url = f"{GRAPH_BASE}/me/mailFolders/{safe_folder}/messages"
        params: dict[str, Any] = {
            "$top": str(top),
            "$select": select,
            "$orderby": "receivedDateTime desc",
        }

        filters = []
        if filter_sender:
            filters.append(f"from/emailAddress/address eq '{self._odata_escape(filter_sender)}'")
        if filter_subject:
            filters.append(f"contains(subject, '{self._odata_escape(filter_subject)}')")
        if filters:
            params["$filter"] = " and ".join(filters)

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
        return resp.json().get("value", [])

    async def get_message(self, message_id: str) -> dict:
        """Get a single message by ID."""
        headers = await self._headers()
        safe_id = quote(message_id, safe="")
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GRAPH_BASE}/me/messages/{safe_id}",
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
        return resp.json()

    async def list_attachments(self, message_id: str) -> list[dict]:
        """List attachments for a message."""
        headers = await self._headers()
        safe_id = quote(message_id, safe="")
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GRAPH_BASE}/me/messages/{safe_id}/attachments",
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
        return resp.json().get("value", [])

    # ── Mail reply / send ────────────────────────────────────

    async def reply_to_message(self, message_id: str, body: str) -> None:
        """Reply to a message (sender only). Requires Mail.Send."""
        require_scope(self._granted_scopes, "Mail.Send")
        headers = await self._headers()
        safe_id = quote(message_id, safe="")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{GRAPH_BASE}/me/messages/{safe_id}/reply",
                headers=headers,
                json={"message": {"body": {"contentType": "Text", "content": body}}},
                timeout=15,
            )
            resp.raise_for_status()

    async def reply_all_to_message(self, message_id: str, body: str) -> None:
        """Reply-all to a message. Requires Mail.Send."""
        require_scope(self._granted_scopes, "Mail.Send")
        headers = await self._headers()
        safe_id = quote(message_id, safe="")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{GRAPH_BASE}/me/messages/{safe_id}/replyAll",
                headers=headers,
                json={"message": {"body": {"contentType": "Text", "content": body}}},
                timeout=15,
            )
            resp.raise_for_status()

    async def send_mail(
        self,
        to_recipients: list[str],
        subject: str,
        body: str,
        cc_recipients: list[str] | None = None,
    ) -> None:
        """Send a new email (for custom recipient mode). Requires Mail.Send."""
        require_scope(self._granted_scopes, "Mail.Send")
        headers = await self._headers()
        message: dict[str, Any] = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": r}} for r in to_recipients],
        }
        if cc_recipients:
            message["ccRecipients"] = [{"emailAddress": {"address": r}} for r in cc_recipients]

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{GRAPH_BASE}/me/sendMail",
                headers=headers,
                json={"message": message, "saveToSentItems": True},
                timeout=15,
            )
            resp.raise_for_status()
