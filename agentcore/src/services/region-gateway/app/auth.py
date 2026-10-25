"""Simple API-key authentication for hub → spoke calls.

Each spoke has its own API key (the same x-api-key mechanism used by
model-service and other microservices). The gateway reads each region's
key from config (loaded from regions.json or Key Vault) and attaches it
as the ``x-api-key`` header when proxying requests.

No Azure Managed Identity. No cross-tenant token dance. Just HTTPS + API key.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config import RegionEntry

logger = logging.getLogger(__name__)


@dataclass
class SpokeAuthService:
    """Provides the correct x-api-key header value for a given spoke region."""

    def get_api_key(self, region: RegionEntry) -> str | None:
        """Return the API key for the given region, or None if not configured.

        When api_key is empty/None (e.g. hub calling itself, or dev mode),
        no auth header is added — the spoke's own cookie/session auth handles it.
        """
        if not region.api_key:
            logger.debug("No API key for region '%s', skipping auth header", region.code)
            return None
        return region.api_key


# Singleton
spoke_auth = SpokeAuthService()
