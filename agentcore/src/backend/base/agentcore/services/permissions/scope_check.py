"""Permission scope checks for Microsoft Graph connectors (Outlook / SharePoint / Teams).

The connectors auto-discover what permissions the Azure AD app registration has been
granted by parsing data Microsoft already returns:

- **Delegated flows (Outlook, Teams)**: the OAuth token response contains a ``scope``
  field listing the *actually granted* scopes (which may be fewer than what we asked
  for if the app reg was set up with reduced permissions).
- **App-only flows (SharePoint)**: the access token JWT contains a ``roles`` claim
  with the granted Application permissions.

Each connector persists the discovered list (``granted_scopes`` or ``granted_roles``)
into its existing ``provider_config`` JSON column. Read paths never check this list —
they always run. Write paths call :func:`require_scope` which raises
:class:`ConnectorPermissionError` (translated to HTTP 403 at the API boundary) when
the required permission is missing.

Permissive fallback: when the granted list is empty (e.g. legacy connectors created
before this module existed, or token-response parsing failed), every check passes.
This guarantees zero regression for existing deployments — the gates only activate
once a connector has been (re)linked under the new code path.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Iterable

from loguru import logger


class ConnectorPermissionError(Exception):
    """Raised when a connector lacks an Azure AD permission required for an operation.

    Attributes:
        scope: the missing Microsoft Graph permission (e.g. ``"Mail.Send"``).
    """

    def __init__(self, scope: str, message: str | None = None) -> None:
        self.scope = scope
        super().__init__(
            message
            or f"{scope} permission not granted on this connector's app registration"
        )


def parse_jwt_roles(access_token: str) -> list[str]:
    """Decode the payload segment of a JWT access token and return the ``roles`` claim.

    Used for app-only (client_credentials) tokens issued by Azure AD, where the
    granted Application permissions are surfaced as the ``roles`` claim. We do NOT
    verify the signature — the token already came over HTTPS from
    ``login.microsoftonline.com`` and is not used for authorization on our side; we
    only read the claim to learn which write features should be exposed.

    Returns an empty list on any decode failure (malformed token, missing claim,
    base64 padding error). Callers treat empty as "permissive fallback".
    """
    if not access_token:
        return []
    try:
        segments = access_token.split(".")
        if len(segments) < 2:
            logger.warning("JWT roles decode: token has fewer than 2 segments")
            return []
        payload_b64 = segments[1]
        # urlsafe_b64decode requires correct padding
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(payload_bytes)
    except (ValueError, binascii.Error, json.JSONDecodeError) as exc:
        logger.warning(f"JWT roles decode failed: {exc!r}")
        return []
    # JWT body must be an object; if Microsoft ever returns a non-object
    # payload (array, scalar) fail closed to an empty list rather than
    # raising AttributeError on .get(). This is defensive — Microsoft is
    # consistent in practice, but ill-formed tokens shouldn't crash the
    # caller.
    if not isinstance(payload, dict):
        return []
    roles = payload.get("roles", [])
    if not isinstance(roles, list):
        return []
    # Coerce to list[str] and drop falsy entries
    return [str(r) for r in roles if r]


_SCOPE_PREFIXES = (
    "https://graph.microsoft.com/",
    "https://outlook.office.com/",
    "https://outlook.office365.com/",
    "api://",  # custom-API scopes also normalize away the resource prefix
)


def parse_oauth_scopes(scope_str: str | None) -> list[str]:
    """Parse the space-separated ``scope`` field from an OAuth token response.

    Microsoft returns granted scopes in one of two equivalent forms depending
    on the app registration's audience and access-token version:

    * Short names (single-tenant work apps with v1 tokens)::
          "Mail.Read User.Read offline_access"

    * Full resource URIs (multi-tenant / personal-account apps with v2 tokens)::
          "https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/User.Read offline_access"

    We normalize to the short form on parse so the comparison ``"Mail.Send" in
    granted`` works regardless of which form Microsoft used. The same
    permission must therefore be matched by exactly one string in the list,
    not both forms. The literal ``.default`` token (from the OAuth request) is
    dropped because it isn't a real granted scope — it's the request marker.

    Returns ``[]`` for ``None`` or empty input.
    """
    if not scope_str:
        return []
    normalized: list[str] = []
    for raw in scope_str.split():
        s = raw.strip()
        if not s:
            continue
        # Strip Graph / Outlook / api:// resource prefix if present
        for prefix in _SCOPE_PREFIXES:
            if s.lower().startswith(prefix.lower()):
                s = s[len(prefix):]
                break
        # Drop the .default request marker — not a real granted scope
        if s == ".default":
            continue
        normalized.append(s)
    return normalized


def require_scope(granted: Iterable[str] | None, required: str) -> None:
    """Raise :class:`ConnectorPermissionError` if ``required`` is not in ``granted``.

    Three distinct states (so legacy compatibility doesn't paper over real
    permission gaps):

    * ``granted is None``  — legacy connector (the ``granted_scopes`` field
      didn't exist yet when the account was linked). Permissive fallback —
      no-op, the operation is allowed. Graph 403 safety net catches genuine
      lack of permission.
    * ``granted == []``    — OAuth completed but Microsoft returned no scope
      string (or the post-OAuth parse produced an empty list). This is a
      *known-empty* state, not a *legacy-unknown* state, so we treat it
      strictly: raise.
    * ``granted == [...]`` — normal case, check membership.
    """
    if granted is None:
        return  # legacy / pre-feature connector — permissive fallback
    granted_list = list(granted)
    if required not in granted_list:
        raise ConnectorPermissionError(required)


def has_scope(granted: Iterable[str] | None, required: str) -> bool:
    """Non-raising variant of :func:`require_scope`, for UI/output filtering.

    Same three-state semantics as :func:`require_scope`: ``None`` is permissive
    (legacy), ``[]`` is strict (OAuth returned nothing), populated list is
    membership check.
    """
    if granted is None:
        return True  # legacy permissive
    return required in list(granted)


def require_any_scope(
    granted: Iterable[str] | None,
    options: Iterable[str],
) -> None:
    """Raise :class:`ConnectorPermissionError` unless *any one* of ``options`` is
    in ``granted``.

    Useful when a single Graph operation can be authorised by more than one
    Application or Delegated permission — for example, SharePoint writes
    accept either ``Sites.ReadWrite.All`` (broad), ``Files.ReadWrite.All``
    (file-scoped), or ``Sites.Selected`` (per-site grants applied outside
    the JWT role list). ``require_scope`` is too strict for these cases.

    Same three-state semantics as :func:`require_scope`:

    * ``granted is None``  — legacy connector, permissive (no-op).
    * ``granted == []``    — known-empty, fail strict against ``options[0]``
      so callers see the canonical missing scope name in the error.
    * ``granted == [...]`` — pass if intersect non-empty; else raise naming
      the first option (the documented "preferred" permission).
    """
    options_list = list(options)
    if not options_list:
        msg = "require_any_scope: options must be non-empty"
        raise ValueError(msg)
    if granted is None:
        return  # legacy permissive
    granted_list = list(granted)
    if any(opt in granted_list for opt in options_list):
        return
    # Surface the first/preferred option as the missing scope in the error.
    raise ConnectorPermissionError(options_list[0])


def has_any_scope(
    granted: Iterable[str] | None,
    options: Iterable[str],
) -> bool:
    """Non-raising variant of :func:`require_any_scope` for UI/output filtering.

    Same three-state semantics — ``None`` is permissive (legacy True),
    ``[]`` is strict (False), populated list is intersection check.
    """
    options_list = list(options)
    if not options_list:
        return False
    if granted is None:
        return True  # legacy permissive
    granted_list = list(granted)
    return any(opt in granted_list for opt in options_list)


# ── Graph error translation ────────────────────────────────────────────────


_GRAPH_403_BODY_HINTS = (
    "insufficient privileges",
    "forbidden",
    "accessdenied",
    "access denied",
    "authorization_requestdenied",
    "applicationprivilegerequired",
)


def is_graph_permission_error(status: int, body: str | bytes = "") -> bool:
    """Detect a Microsoft Graph response that indicates a missing permission.

    A bare 403 always counts. We additionally inspect the response body for
    Graph's documented permission-denial codes/strings so that 401s carrying
    ``"Insufficient privileges"`` are also caught (rare but observed when
    admin consent is partial).
    """
    if status == 403:
        return True
    if status not in (401, 403):
        return False
    if isinstance(body, bytes):
        try:
            body = body.decode("utf-8", "replace")
        except Exception:
            return False
    text = (body or "").lower()
    return any(hint in text for hint in _GRAPH_403_BODY_HINTS)


def graph_permission_error_message(
    required_scope: str,
    *,
    operation: str = "operation",
    graph_status: int | None = None,
    graph_body: str | bytes = "",
) -> str:
    """Build a user-friendly message when Graph rejects with a permission error.

    Use this at the *boundary* (API handlers, tool methods) when our local
    ``require_scope`` gate passed but Microsoft still returned 403 — typically
    because the admin revoked the permission since the token was issued, or
    the locally-stored ``granted_scopes`` list is empty (legacy / permissive
    fallback) and we can't tell ahead of time.

    The message names the likely missing scope, explains the recovery path,
    and includes a short Graph snippet for support diagnostics — all without
    leaking the full raw upstream JSON.
    """
    if isinstance(graph_body, bytes):
        try:
            graph_body = graph_body.decode("utf-8", "replace")
        except Exception:
            graph_body = ""
    snippet = (graph_body or "").strip()
    snippet = snippet[:200] + ("…" if len(snippet) > 200 else "")
    status_part = f" (Graph returned {graph_status})" if graph_status else ""
    suffix = f" Graph response: {snippet}" if snippet else ""
    return (
        f"Cannot complete {operation}: the connector's app registration is "
        f"missing the {required_scope} permission, or it was revoked after "
        f"the connector was linked{status_part}. Ask your tenant admin to "
        f"grant {required_scope} (with admin consent), then disconnect and "
        f"reconnect the account.{suffix}"
    )
