"""Orchestrator Outlook integration — port of MiBuddy's `/outlook/...` routes.

Kept separate from agentcore's existing `outlook_chat` router (different
use-case, must not be touched). Mounted under `/api/outlook-orch`.

Flow:
  1. Frontend opens popup → GET /api/outlook-orch/auth/login
       → 302 to login.microsoftonline.com with PKCE challenge
  2. Microsoft redirects back to /api/outlook-orch/auth/callback
       → exchange code (+ code_verifier) for access_token
       → encrypt + store token in OutlookTokenManager keyed by user_id
       → set `outlook_session` HTTP-only cookie
       → postMessage success to opener window, then close popup
  3. GET /api/outlook-orch/status → is this user connected?
  4. POST /api/outlook-orch/{get_emails|search_emails|get_calendar|send_email}
     — all take `access_token` in body like MiBuddy, but server can also
     resolve it from the stored token if the frontend passes nothing.
"""
from __future__ import annotations

import base64
import hashlib
import html
import logging
import secrets
import threading
import time
from typing import Any, Dict, Optional
from urllib.parse import quote_plus, urlparse
from uuid import uuid4

import requests
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.auth.utils import get_current_user_by_jwt
from agentcore.services.outlook_orch.intent_router import handle_outlook_intent
from agentcore.services.outlook_orch.outlook_service import OutlookService
from agentcore.services.outlook_orch.token_manager import outlook_token_manager


async def _resolve_current_user_from_request(request: Request, db):
    """Resolve the current user from cookie, Authorization header, OR query
    param. The FastAPI-standard `CurrentActiveUser` dependency only reads the
    Authorization header, which popup windows (opened via `window.open()`) do
    not send. This helper mirrors the pattern used by `teams.py`'s popup
    OAuth login so cookies work for browser-navigation flows.
    """
    auth_header = request.headers.get("Authorization", "")
    bearer_token = (
        auth_header.split(" ", 1)[1] if auth_header.startswith("Bearer ") else None
    )
    cookie_token = request.cookies.get("access_token_ag")
    query_token = request.query_params.get("token")
    resolved_token = cookie_token or bearer_token or query_token
    if not resolved_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
        )
    return await get_current_user_by_jwt(resolved_token, db)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/outlook-orch", tags=["Outlook (Orchestrator)"])

# ── OAuth PKCE state ──────────────────────────────────────────────────
# MiBuddy uses an in-memory dict which works for single-instance deployments.
# For multi-replica K8s, we encrypt the PKCE state (code_verifier + user_id)
# into the `state` URL parameter itself using the same Fernet key as the
# token manager. No in-memory storage needed — works across any number of pods.
_PKCE_STATE_TTL = 600  # seconds

def _get_state_cipher():
    from agentcore.services.outlook_orch.token_manager import _get_or_generate_encryption_key
    from cryptography.fernet import Fernet
    return Fernet(_get_or_generate_encryption_key())


_OUTLOOK_SCOPES = " ".join([
    "https://graph.microsoft.com/User.Read",
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/Mail.Read.Shared",
    "https://graph.microsoft.com/Mail.ReadBasic",
    "https://graph.microsoft.com/Mail.Send",
    "https://graph.microsoft.com/Calendars.Read",
    "https://graph.microsoft.com/Calendars.Read.Shared",
    "https://graph.microsoft.com/Calendars.ReadBasic",
    "offline_access",
])

_AUTH_SUCCESS_HTML = """<!DOCTYPE html>
<html><head><title>Connecting...</title></head>
<body>
<script>
  try { if (window.opener) { window.opener.postMessage({type:'OUTLOOK_AUTH_SUCCESS'}, '*'); } } catch(e) {}
  window.close();
</script>
<p>Outlook connected. You may close this window.</p>
</body></html>"""

# NOTE: the error template uses plain string replacement (not str.format)
# because the JS payload contains braces like {type:...} which str.format
# mis-parses as field specifiers and raises
# "unexpected '{' in field name".
_AUTH_ERROR_HTML = """<!DOCTYPE html>
<html><head><title>Auth Error</title></head>
<body>
<script>
  try { if (window.opener) { window.opener.postMessage({type:'OUTLOOK_AUTH_ERROR',error:'__OUTLOOK_ERR__'}, '*'); } } catch(e) {}
  window.close();
</script>
<p>Authentication failed: __OUTLOOK_ERR__. You may close this window.</p>
</body></html>"""


def _build_redirect_uri(request: Request) -> str:
    """Build the redirect URI deterministically from the incoming request.

    An explicit `OUTLOOK_ORCH_REDIRECT_URI` env var takes precedence so prod
    deployments behind a reverse proxy don't depend on request.url.
    """
    import os
    override = os.environ.get("OUTLOOK_ORCH_REDIRECT_URI", "").strip().strip("'\"")
    if override:
        return override
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/outlook-orch/auth/callback"


def _is_request_secure(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    fwd = request.headers.get("x-forwarded-proto", "")
    return "https" in fwd.lower()


def _html_escape(s: str) -> str:
    return html.escape(s, quote=True)


# ══════════════════════════════════════════════════════════════════════
#   OAUTH: LOGIN + CALLBACK
# ══════════════════════════════════════════════════════════════════════

@router.get("/auth/login")
async def outlook_auth_login(
    request: Request,
    session: DbSession,
) -> RedirectResponse:
    """Kick off Authorization Code + PKCE flow.

    Opened via `window.open()`, so we resolve the user from the
    `access_token_ag` cookie (popups don't send Authorization headers).
    """
    import json
    current_user = await _resolve_current_user_from_request(request, session)
    user_id = str(current_user.id)

    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("ascii")).digest(),
    ).rstrip(b"=").decode("ascii")

    # Encrypt PKCE state into the `state` param so ANY pod can read it back.
    state_payload = json.dumps({"cv": code_verifier, "uid": user_id, "ts": time.time()})
    state = _get_state_cipher().encrypt(state_payload.encode()).decode()

    redirect_uri = _build_redirect_uri(request)
    logger.info(f"Outlook OAuth login: redirect_uri={redirect_uri}")

    from agentcore.services.outlook_orch.outlook_service import _get_credentials
    tenant, client_id, _ = _get_credentials()

    auth_url = (
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
        f"?client_id={client_id}"
        f"&response_type=code"
        f"&redirect_uri={quote_plus(redirect_uri)}"
        f"&scope={quote_plus(_OUTLOOK_SCOPES)}"
        f"&state={state}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
        f"&prompt=select_account"
    )
    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/auth/callback")
async def outlook_auth_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
) -> HTMLResponse:
    """Completes Authorization Code + PKCE flow and sets cookie session.

    Exact copy of MiBuddy's `/outlook/auth/callback` logic.
    """
    def error_response(reason: str) -> HTMLResponse:
        safe_reason = _html_escape(reason).replace("'", "\\'")
        return HTMLResponse(
            content=_AUTH_ERROR_HTML.replace("__OUTLOOK_ERR__", safe_reason),
        )

    if error:
        logger.warning(f"Outlook OAuth error from Microsoft: {error} - {error_description}")
        return error_response(error)

    import json
    if not code or not state:
        return error_response("missing_code_or_state")

    # Decrypt the PKCE state from the `state` URL param.
    try:
        state_data = json.loads(_get_state_cipher().decrypt(state.encode()))
    except Exception:
        logger.warning("Outlook OAuth callback: failed to decrypt state param")
        return error_response("invalid_state")

    if time.time() - state_data.get("ts", 0) > _PKCE_STATE_TTL:
        return error_response("state_expired")

    code_verifier = state_data["cv"]
    user_id = state_data.get("uid")

    # Use the SAME deterministic redirect_uri that was used during /authorize
    redirect_uri = _build_redirect_uri(request)
    logger.info(f"Outlook OAuth callback: redirect_uri={redirect_uri}")

    # Direct token exchange — exact MiBuddy pattern
    from agentcore.services.outlook_orch.outlook_service import _get_credentials
    tenant, client_id, client_secret = _get_credentials()

    try:
        token_resp = requests.post(
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
    except Exception as exc:
        logger.error(f"Network error during token exchange: {exc}")
        return error_response("token_exchange_network_error")

    if token_resp.status_code != 200:
        logger.error(f"Token exchange failed ({token_resp.status_code}): {token_resp.text[:500]}")
        return error_response("token_exchange_failed")

    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    expires_in = int(token_data.get("expires_in", 3600))

    if not access_token:
        return error_response("no_access_token_in_response")

    if not user_id:
        user_info = OutlookService.validate_access_token(access_token)
        if user_info:
            user_id = user_info.get("id") or user_info.get("userPrincipalName")

    if not user_id:
        return error_response("cannot_identify_user")

    outlook_token_manager.store_token(user_id, access_token, expires_in)

    # Encrypt user_id + access_token into the cookie so ANY pod can read
    # them back — no in-memory token manager lookup needed.
    import json
    session_payload = json.dumps({
        "uid": user_id,
        "tok": access_token,
        "exp": time.time() + expires_in,
    })
    encrypted_session = _get_state_cipher().encrypt(session_payload.encode()).decode()

    is_secure = _is_request_secure(request)
    response = HTMLResponse(content=_AUTH_SUCCESS_HTML)
    response.set_cookie(
        key="outlook_session",
        value=encrypted_session,
        httponly=True,
        secure=is_secure,
        samesite="lax",
        max_age=expires_in,
        path="/",
    )
    return response


# ══════════════════════════════════════════════════════════════════════
#   STATUS / DISCONNECT
# ══════════════════════════════════════════════════════════════════════

def _decrypt_outlook_cookie(request: Request) -> Optional[str]:
    """Decrypt the outlook_session cookie to get the user_id (legacy)."""
    payload = _decrypt_outlook_session(request)
    return payload.get("uid") if payload else None


def _decrypt_outlook_session(request: Request) -> Optional[Dict[str, Any]]:
    """Decrypt the outlook_session cookie to get {uid, tok, exp}."""
    import json
    cookie = request.cookies.get("outlook_session")
    if not cookie:
        return None
    try:
        raw = _get_state_cipher().decrypt(cookie.encode()).decode()
        data = json.loads(raw)
        if data.get("exp", 0) < time.time():
            return None
        return data
    except Exception:
        return None


def get_outlook_token_from_request(request: Request) -> Optional[str]:
    """Return the Outlook access_token from the encrypted session cookie.

    Any pod can call this — no dependency on in-memory token manager.
    """
    payload = _decrypt_outlook_session(request)
    return payload.get("tok") if payload else None


@router.get("/status")
async def outlook_status(
    request: Request, current_user: CurrentActiveUser,
) -> JSONResponse:
    user_id = str(current_user.id)
    cookie_user = _decrypt_outlook_cookie(request)
    # Cookie proves the user completed OAuth — trust it for status display.
    # The token manager is in-memory per pod, so checking it would give
    # false negatives on pods that didn't handle the original callback.
    is_connected = bool(cookie_user and cookie_user == user_id)
    return JSONResponse(content={"connected": is_connected}, status_code=200)


@router.post("/disconnect")
async def outlook_disconnect(
    request: Request, current_user: CurrentActiveUser,
) -> JSONResponse:
    user_id = str(current_user.id)
    outlook_token_manager.delete_token(user_id)
    response = JSONResponse(
        content={"message": "Outlook disconnected successfully"}, status_code=200,
    )
    response.delete_cookie("outlook_session", path="/")
    return response


# ══════════════════════════════════════════════════════════════════════
#   DATA ENDPOINTS  (access_token may come from body OR server-stored)
# ══════════════════════════════════════════════════════════════════════

def _resolve_token(
    body_token: Optional[str], current_user
) -> Optional[str]:
    """Prefer token from request body (MiBuddy-style), else use server store."""
    if body_token:
        return body_token
    return outlook_token_manager.get_token(str(current_user.id))


class ValidateTokenReq(BaseModel):
    access_token: Optional[str] = None


class GetEmailsReq(BaseModel):
    access_token: Optional[str] = None
    top: int = 10
    skip: int = 0
    folder: str = "inbox"
    search: Optional[str] = None
    unread_only: bool = False
    received_after: Optional[str] = None
    received_before: Optional[str] = None


class SearchEmailsReq(BaseModel):
    access_token: Optional[str] = None
    query: str
    top: int = 10


class GetCalendarReq(BaseModel):
    access_token: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    top: int = 10


class SendEmailReq(BaseModel):
    access_token: Optional[str] = None
    to: list[str]
    subject: str
    body: str = ""
    body_type: str = "HTML"


@router.post("/validate_token")
async def validate_token(req: ValidateTokenReq, current_user: CurrentActiveUser):
    access_token = _resolve_token(req.access_token, current_user)
    if not access_token:
        return JSONResponse(
            content={"valid": False, "error": "No access token available"},
            status_code=401,
        )
    user_info = OutlookService.validate_access_token(access_token)
    if user_info:
        return {"valid": True, "user": user_info}
    return JSONResponse(
        content={"valid": False, "error": "Invalid or expired token"},
        status_code=401,
    )


@router.post("/get_emails")
async def get_emails(req: GetEmailsReq, current_user: CurrentActiveUser):
    access_token = _resolve_token(req.access_token, current_user)
    if not access_token:
        return JSONResponse(content={"error": "Not connected to Outlook"}, status_code=401)
    emails = OutlookService.get_emails(
        access_token,
        top=req.top,
        skip=req.skip,
        folder=req.folder,
        search=req.search,
        unread_only=req.unread_only,
        received_after=req.received_after,
        received_before=req.received_before,
    )
    if emails is None:
        return JSONResponse(content={"error": "Failed to retrieve emails"}, status_code=500)
    return {"success": True, "emails": emails, "count": len(emails)}


@router.post("/search_emails")
async def search_emails(req: SearchEmailsReq, current_user: CurrentActiveUser):
    access_token = _resolve_token(req.access_token, current_user)
    if not access_token:
        return JSONResponse(content={"error": "Not connected to Outlook"}, status_code=401)
    if not req.query:
        return JSONResponse(content={"error": "query is required"}, status_code=400)
    emails = OutlookService.search_emails(access_token, req.query, req.top)
    if emails is None:
        return JSONResponse(content={"error": "Failed to search emails"}, status_code=500)
    return {"success": True, "emails": emails, "count": len(emails)}


@router.post("/get_calendar")
async def get_calendar(req: GetCalendarReq, current_user: CurrentActiveUser):
    access_token = _resolve_token(req.access_token, current_user)
    if not access_token:
        return JSONResponse(content={"error": "Not connected to Outlook"}, status_code=401)
    events = OutlookService.get_calendar_events(
        access_token, req.start_date, req.end_date, req.top,
    )
    if events is None:
        return JSONResponse(
            content={"error": "Failed to retrieve calendar events"}, status_code=500,
        )
    return {"success": True, "events": events, "count": len(events)}


class IntentCheckReq(BaseModel):
    message: str


@router.post("/intent")
async def outlook_intent_check(
    req: IntentCheckReq, current_user: CurrentActiveUser,
):
    """Frontend precheck — does this message look like an Outlook query?

    If yes and the user is connected, returns the Graph-backed markdown
    reply the UI can render as-is. If no, returns ``{matched: False}`` so
    the caller continues with the normal LLM chat flow.
    """
    result = handle_outlook_intent(str(current_user.id), req.message)
    if result is None:
        return {"matched": False}
    return {"matched": True, "kind": result.kind, "markdown": result.markdown}


@router.post("/send_email")
async def send_email(req: SendEmailReq, current_user: CurrentActiveUser):
    access_token = _resolve_token(req.access_token, current_user)
    if not access_token:
        return JSONResponse(content={"error": "Not connected to Outlook"}, status_code=401)
    if not req.to or not req.subject:
        return JSONResponse(
            content={"error": "'to' and 'subject' are required"}, status_code=400,
        )
    ok = OutlookService.send_email(access_token, req.to, req.subject, req.body, req.body_type)
    if ok:
        return {"success": True, "message": "Email sent successfully"}
    return JSONResponse(content={"error": "Failed to send email"}, status_code=500)
