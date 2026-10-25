"""
Outlook Service for backend token validation and email operations via
Microsoft Graph API.

Verbatim port of MiBuddy's `backend/outlook/outlook_service.py`. Reads
credentials from `SHAREPOINT_*` env vars (the MiBuddy AD app — same one
the orchestrator's SharePoint picker uses), falling back to legacy
`AZURE_AD_*` / `AZURE_*` names for parity with MiBuddy-style configs.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


def _get_credentials() -> tuple[str, str, str]:
    """Resolve (tenant_id, client_id, client_secret).

    Preference order (so this works with both MiBuddy-style .env files and
    agentcore's newer SHAREPOINT_* naming):
      1. SHAREPOINT_TENANT_ID / SHAREPOINT_CLIENT_ID / SHAREPOINT_CLIENT_SECRET
      2. AZURE_AD_TENANT_ID   / AZURE_AD_CLIENT_ID   / AZURE_AD_CLIENT_SECRET
      3. AZURE_TENANT_ID      / AZURE_CLIENT_ID      / AZURE_CLIENT_SECRET
    """
    tenant = (
        os.getenv("SHAREPOINT_TENANT_ID", "")
        or os.getenv("AZURE_AD_TENANT_ID", "")
        or os.getenv("AZURE_TENANT_ID", "")
    )
    client = (
        os.getenv("SHAREPOINT_CLIENT_ID", "")
        or os.getenv("AZURE_AD_CLIENT_ID", "")
        or os.getenv("AZURE_CLIENT_ID", "")
    )
    secret = (
        os.getenv("SHAREPOINT_CLIENT_SECRET", "")
        or os.getenv("AZURE_AD_CLIENT_SECRET", "")
        or os.getenv("AZURE_CLIENT_SECRET", "")
    )
    return tenant, client, secret


class OutlookTokenExpiredError(Exception):
    """Raised when a Graph API call returns 401 (token expired/revoked)."""


def _check_token_expired(response, context: str = ""):
    """Raise OutlookTokenExpiredError if the Graph response is 401."""
    if response.status_code == 401:
        logger.warning(
            f"Token expired/revoked during {context}: {response.status_code}"
        )
        raise OutlookTokenExpiredError(f"Access token expired during {context}")


class OutlookService:
    """Service for Outlook operations via Microsoft Graph API."""

    GRAPH_API_ENDPOINT = "https://graph.microsoft.com/v1.0"

    @staticmethod
    def _token_endpoint() -> str:
        tenant, _, _ = _get_credentials()
        return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

    # ─────────────────────────── Token / auth ───────────────────────────

    @staticmethod
    def validate_access_token(access_token: str) -> Optional[Dict[str, Any]]:
        """Validate token by calling Graph /me. Returns user info or None."""
        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            response = requests.get(
                f"{OutlookService.GRAPH_API_ENDPOINT}/me",
                headers=headers,
                timeout=10,
            )
            if response.status_code == 200:
                return response.json()
            logger.warning(f"Token validation failed: {response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Error validating token: {e}")
            return None

    @staticmethod
    def exchange_code_for_token(
        auth_code: str, redirect_uri: str, code_verifier: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Exchange an auth-code for an access token (confidential client).

        Matches MiBuddy: always sends client_secret. If code_verifier is
        provided (PKCE), it is included alongside the secret.
        """
        try:
            _, client_id, client_secret = _get_credentials()
            data = {
                "client_id": client_id,
                "client_secret": client_secret,
                "code": auth_code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "scope": (
                    "User.Read Mail.Read Mail.Send "
                    "Calendars.Read offline_access"
                ),
            }
            if code_verifier:
                data["code_verifier"] = code_verifier

            response = requests.post(
                OutlookService._token_endpoint(),
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
            if response.status_code == 200:
                return response.json()
            logger.error(
                f"Token exchange failed: {response.status_code} - {response.text[:500]}"
            )
            return None
        except Exception as e:
            logger.error(f"Error exchanging code for token: {e}")
            return None

    # ─────────────────────────── Email retrieval ────────────────────────

    @staticmethod
    def get_emails(
        access_token: str,
        top: int = 10,
        skip: int = 0,
        folder: str = "inbox",
        search: Optional[str] = None,
        unread_only: bool = False,
        received_after: Optional[str] = None,
        received_before: Optional[str] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """Retrieve emails from a mailbox folder (inbox, drafts, sent, ...)."""
        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }

            filters: List[str] = []
            if unread_only or received_after or received_before:
                headers["ConsistencyLevel"] = "eventual"

            params: Dict[str, Any] = {
                "$top": min(top, 50),
                "$skip": skip,
                "$orderby": "receivedDateTime desc",
                "$select": (
                    "id,subject,from,toRecipients,receivedDateTime,"
                    "bodyPreview,hasAttachments,importance,isRead,"
                    "inferenceClassification"
                ),
            }

            if received_after:
                filters.append(f"receivedDateTime ge {received_after}")
            if received_before:
                filters.append(f"receivedDateTime lt {received_before}")
            if unread_only:
                filters.append("isRead eq false")
            if filters:
                params["$filter"] = " and ".join(filters)
                params["$count"] = "true"
            if search:
                params["$search"] = f'"{search}"'

            endpoint = (
                f"{OutlookService.GRAPH_API_ENDPOINT}"
                f"/me/mailFolders/{folder}/messages"
            )
            response = requests.get(endpoint, headers=headers, params=params, timeout=30)

            if response.status_code == 200:
                return response.json().get("value", [])
            _check_token_expired(response, "get_emails")
            logger.error(
                f"Failed to retrieve emails: {response.status_code} - {response.text}"
            )
            return None
        except OutlookTokenExpiredError:
            raise
        except Exception as e:
            logger.error(f"Error retrieving emails: {e}")
            return None

    @staticmethod
    def search_emails_by_sender(
        access_token: str, sender: str, top: int = 10,
    ) -> Optional[List[Dict[str, Any]]]:
        """Search across mailbox by sender name/email using $search."""
        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            params = {
                "$search": f'"from:{sender}"',
                "$top": min(top, 50),
                "$select": (
                    "id,subject,from,toRecipients,receivedDateTime,"
                    "bodyPreview,hasAttachments,importance,isRead"
                ),
            }
            response = requests.get(
                f"{OutlookService.GRAPH_API_ENDPOINT}/me/messages",
                headers=headers, params=params, timeout=30,
            )
            if response.status_code == 200:
                return response.json().get("value", [])
            _check_token_expired(response, "search_emails_by_sender")
            logger.error(
                f"Failed to search by sender: {response.status_code} - {response.text}"
            )
            return None
        except OutlookTokenExpiredError:
            raise
        except Exception as e:
            logger.error(f"Error searching emails by sender: {e}")
            return None

    @staticmethod
    def get_email_by_id(
        access_token: str, message_id: str,
    ) -> Optional[Dict[str, Any]]:
        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            response = requests.get(
                f"{OutlookService.GRAPH_API_ENDPOINT}/me/messages/{message_id}",
                headers=headers, timeout=20,
            )
            if response.status_code == 200:
                return response.json()
            _check_token_expired(response, "get_email_by_id")
            logger.error(f"Failed to retrieve email: {response.status_code}")
            return None
        except OutlookTokenExpiredError:
            raise
        except Exception as e:
            logger.error(f"Error retrieving email: {e}")
            return None

    @staticmethod
    def search_emails(
        access_token: str, query: str, top: int = 10,
    ) -> Optional[List[Dict[str, Any]]]:
        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            params = {
                "$search": f'"{query}"',
                "$top": min(top, 50),
                "$orderby": "receivedDateTime desc",
            }
            response = requests.get(
                f"{OutlookService.GRAPH_API_ENDPOINT}/me/messages",
                headers=headers, params=params, timeout=30,
            )
            if response.status_code == 200:
                return response.json().get("value", [])
            _check_token_expired(response, "search_emails")
            logger.error(f"Failed to search emails: {response.status_code}")
            return None
        except OutlookTokenExpiredError:
            raise
        except Exception as e:
            logger.error(f"Error searching emails: {e}")
            return None

    # ─────────────────────────── Calendar ──────────────────────────────

    @staticmethod
    def get_calendar_events(
        access_token: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        top: int = 10,
    ) -> Optional[List[Dict[str, Any]]]:
        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Prefer": 'outlook.timezone="India Standard Time"',
            }
            if not start_date:
                start_date = datetime.utcnow().isoformat() + "Z"
            if not end_date:
                end_date = (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"

            requested_top = max(1, min(int(top or 10), 200))
            params = {
                "$top": min(requested_top, 50),
                "$orderby": "start/dateTime",
                "$select": (
                    "id,subject,start,end,location,attendees,organizer,"
                    "isOnlineMeeting,onlineMeetingUrl,isCancelled,"
                    "responseStatus,showAs"
                ),
                "startDateTime": start_date,
                "endDateTime": end_date,
            }
            endpoint = f"{OutlookService.GRAPH_API_ENDPOINT}/me/calendarView"

            collected: List[Dict[str, Any]] = []
            next_url = endpoint
            next_params: Optional[Dict[str, Any]] = params

            while next_url and len(collected) < requested_top:
                response = requests.get(
                    next_url, headers=headers, params=next_params, timeout=30,
                )
                if response.status_code != 200:
                    _check_token_expired(response, "get_calendar_events")
                    logger.error(
                        f"Failed to retrieve calendar: {response.status_code}"
                    )
                    return None
                data = response.json()
                batch = data.get("value", [])
                if not batch:
                    break
                collected.extend(batch)
                next_url = data.get("@odata.nextLink")
                next_params = None  # nextLink already has query params
            return collected[:requested_top]
        except OutlookTokenExpiredError:
            raise
        except Exception as e:
            logger.error(f"Error retrieving calendar events: {e}")
            return None

    # ─────────────────────────── Send ──────────────────────────────────

    @staticmethod
    def send_email(
        access_token: str,
        to_recipients: List[str],
        subject: str,
        body: str,
        body_type: str = "HTML",
    ) -> bool:
        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            message = {
                "message": {
                    "subject": subject,
                    "body": {"contentType": body_type, "content": body},
                    "toRecipients": [
                        {"emailAddress": {"address": e}} for e in to_recipients
                    ],
                }
            }
            response = requests.post(
                f"{OutlookService.GRAPH_API_ENDPOINT}/me/sendMail",
                headers=headers, json=message, timeout=30,
            )
            if response.status_code == 202:
                logger.info("Email sent successfully")
                return True
            logger.error(
                f"Failed to send email: {response.status_code} - {response.text}"
            )
            return False
        except Exception as e:
            logger.error(f"Error sending email: {e}")
            return False
