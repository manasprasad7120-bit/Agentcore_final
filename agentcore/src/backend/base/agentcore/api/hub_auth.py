"""Utility to extract hub caller metadata from proxied requests.

When the region-gateway proxies a dashboard request to a remote region,
it attaches X-Hub-Caller and X-Hub-Request-Id headers for audit trail.
This module extracts that info. The actual auth (x-api-key) is handled
by the existing API key middleware on each deployment.
"""

from __future__ import annotations

import logging

from fastapi import Request

logger = logging.getLogger(__name__)


async def verify_hub_request(request: Request) -> str | None:
    """Extract hub caller info from proxied requests.

    Returns:
        The hub caller user ID from X-Hub-Caller header, or None.
    """
    hub_caller = request.headers.get("X-Hub-Caller")
    hub_request_id = request.headers.get("X-Hub-Request-Id")

    if hub_caller:
        logger.info(
            "Hub request received. caller=%s request_id=%s",
            hub_caller, hub_request_id,
        )

    return hub_caller
