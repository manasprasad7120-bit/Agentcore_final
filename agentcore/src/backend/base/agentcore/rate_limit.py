from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _identity_or_ip_key(request: Request) -> str:
    """Use auth identity when present, otherwise fall back to client IP."""
    auth_header = request.headers.get("authorization", "").strip()
    if auth_header:
        return auth_header

    cookie_token = request.cookies.get("access_token_ag")
    if cookie_token:
        return f"cookie:{cookie_token}"

    return get_remote_address(request)


limiter = Limiter(key_func=_identity_or_ip_key, default_limits=["60/minute"])
