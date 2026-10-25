from __future__ import annotations

import json
import logging
from functools import lru_cache

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Region model
# ---------------------------------------------------------------------------

class RegionEntry(BaseModel):
    code: str                          # ISO 3166-1 alpha-2 e.g. "IN"
    name: str                          # Display name e.g. "India"
    api_url: str                       # Public URL of the region's backend
    is_hub: bool = False               # True for the primary deployment
    api_key: str | None = None         # x-api-key for this region's backend


# ---------------------------------------------------------------------------
# Application settings
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8006
    log_level: str = "info"
    cors_origins: str = "*"

    # Azure Key Vault — required. Region registry is stored as a KV secret.
    key_vault_url: str = ""
    key_vault_regions_secret: str = "agentcore-region-registry"

    # Request timeouts (seconds)
    proxy_timeout: int = 10
    health_check_timeout: int = 5

    model_config = SettingsConfigDict(
        env_prefix="REGION_GATEWAY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ---------------------------------------------------------------------------
# Region registry loader
# ---------------------------------------------------------------------------

_regions: list[RegionEntry] = []


def load_regions(settings: Settings | None = None) -> list[RegionEntry]:
    """Load regions from Azure Key Vault secret.

    The region registry (including API keys) is stored as a JSON string
    in a single Key Vault secret. This ensures API keys are never on disk
    and regions can be updated without redeployment.
    """
    global _regions
    if settings is None:
        settings = get_settings()

    if not settings.key_vault_url:
        raise RuntimeError(
            "REGION_GATEWAY_KEY_VAULT_URL is required. "
            "Region registry must be loaded from Azure Key Vault."
        )

    from azure.keyvault.secrets import SecretClient

    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential(
        exclude_environment_credential=True,
        exclude_interactive_browser_credential=True,
    )

    client = SecretClient(vault_url=settings.key_vault_url, credential=credential)
    secret = client.get_secret(settings.key_vault_regions_secret)

    if not secret.value:
        raise RuntimeError(
            f"Key Vault secret '{settings.key_vault_regions_secret}' is empty. "
            "It must contain the region registry JSON."
        )

    logger.info("Loaded regions from Key Vault secret '%s'", settings.key_vault_regions_secret)
    data = json.loads(secret.value)
    _regions = [RegionEntry(**entry) for entry in data]

    return _regions


def get_regions() -> list[RegionEntry]:
    return _regions


def get_region_by_code(code: str) -> RegionEntry | None:
    code_upper = code.upper()
    for region in _regions:
        if region.code.upper() == code_upper:
            return region
    return None
