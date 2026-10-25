import inspect
import os
import time
from typing import Optional, Any

import redis.asyncio as redis
from redis.asyncio.cluster import RedisCluster
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.credentials import CredentialProvider
from redis.exceptions import ConnectionError, TimeoutError

from agentcore.services.cache.entra_credential_provider import AzureEntraRedisCredentialProvider
from agentcore.services.settings.service import SettingsService

_redis_client: Optional[Any] = None
_redis_signature: Optional[tuple] = None
_redis_credential_provider: Optional[CredentialProvider] = None
_redis_credential_provider_signature: Optional[tuple] = None

# --- circuit breaker -------------------------------------------------------
# When Redis is unreachable every cache call would otherwise wait for connect
# timeouts and retries (tens of seconds per request). After a failure the
# circuit opens for REDIS_CIRCUIT_SECONDS and callers skip Redis immediately,
# falling back to the database / no-op.
REDIS_CIRCUIT_SECONDS = int(os.getenv("REDIS_CIRCUIT_SECONDS", "30") or 30)
_redis_down_until: float = 0.0


def redis_circuit_open() -> bool:
    """True while Redis is considered unavailable (recent connection failure)."""
    return time.monotonic() < _redis_down_until


def mark_redis_down(reason: str = "") -> None:
    global _redis_down_until
    _redis_down_until = time.monotonic() + REDIS_CIRCUIT_SECONDS


def mark_redis_up() -> None:
    global _redis_down_until
    _redis_down_until = 0.0


def redis_configured(settings_service: SettingsService) -> bool:
    """False when REDIS_HOST is empty: Redis-backed caches are then skipped entirely."""
    return bool(str(settings_service.settings.redis_host or "").strip().strip("'\""))


def _redis_cluster_enabled(settings_service: SettingsService) -> bool:
    """Return whether Redis Cluster protocol should be used.

    Priority:
    1) REDIS_CLUSTER_POLICY: enterprise|enterprisecluster -> False, oss|osscluster -> True
    2) REDIS_CLUSTER_ENABLED: true/false style flag
    3) Default: True (OSS cluster behavior)
    """
    policy = str(os.getenv("REDIS_CLUSTER_POLICY", "")).strip().lower()
    if policy in {"enterprise", "enterprisecluster"}:
        return False
    if policy in {"oss", "osscluster"}:
        return True

    raw_flag = os.getenv("REDIS_CLUSTER_ENABLED")
    if raw_flag is not None:
        return str(raw_flag).strip().lower() in {"1", "true", "yes", "on"}

    # Default: cluster protocol only for Azure Managed Redis (Entra scope configured).
    # A plain/local Redis (no Entra scope) is a standalone server.
    return bool((settings_service.settings.redis_entra_scope or "").strip())


def _get_redis_host_port(settings_service: SettingsService) -> tuple[str, int]:
    host = str(settings_service.settings.redis_host or "").strip().strip("'\"")
    if not host:
        msg = "REDIS_HOST must be set for Redis cache."
        raise ValueError(msg)

    raw_port = settings_service.settings.redis_port
    if raw_port in (None, ""):
        raw_port = 6379
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        msg = f"REDIS_PORT must be a valid integer. Got: {raw_port!r}"
        raise ValueError(msg) from exc
    if port <= 0:
        msg = f"REDIS_PORT must be > 0. Got: {port}"
        raise ValueError(msg)
    return host, port


def _get_redis_ssl(settings_service: SettingsService) -> bool:
    raw_ssl = settings_service.settings.redis_ssl
    if isinstance(raw_ssl, bool):
        return raw_ssl
    return str(raw_ssl or "").strip().lower() in {"1", "true", "yes", "on"}

def _get_redis_entra_scope(settings_service: SettingsService) -> str:
    """Return the Entra scope, or "" when Redis runs without Entra ID (plain/local Redis)."""
    return (settings_service.settings.redis_entra_scope or "").strip()


def _get_redis_password() -> str | None:
    """Static password for plain (non-Entra) Redis, if any."""
    return (os.getenv("REDIS_PASSWORD") or "").strip() or None


def get_redis_credential_provider(settings_service: SettingsService) -> CredentialProvider | None:
    global _redis_credential_provider, _redis_credential_provider_signature

    redis_entra_scope = _get_redis_entra_scope(settings_service)
    if not redis_entra_scope:
        # No Entra scope configured -> plain Redis (local demo / self-hosted).
        # Authentication, if any, uses REDIS_PASSWORD instead of Entra tokens.
        return None
    redis_entra_object_id = (settings_service.settings.redis_entra_object_id or "").strip()
    redis_entra_refresh_margin_seconds = settings_service.settings.redis_entra_refresh_margin_seconds
    signature = (
        redis_entra_scope,
        redis_entra_object_id,
        redis_entra_refresh_margin_seconds,
    )

    if _redis_credential_provider is None or _redis_credential_provider_signature != signature:
        if _redis_credential_provider is not None:
            close_provider = getattr(_redis_credential_provider, "close", None)
            if callable(close_provider):
                close_provider()

        _redis_credential_provider = AzureEntraRedisCredentialProvider(
            scope=redis_entra_scope,
            object_id=redis_entra_object_id or None,
            refresh_margin_seconds=redis_entra_refresh_margin_seconds,
        )
        _redis_credential_provider_signature = signature

    return _redis_credential_provider


async def _close_resource(resource: Any) -> None:
    close_fn = getattr(resource, "aclose", None) or getattr(resource, "close", None)
    if not callable(close_fn):
        return
    try:
        result = close_fn()
        if inspect.isawaitable(result):
            await result
    except Exception:
        return


async def reset_redis_client(*, reset_credential_provider: bool = True) -> None:
    """Clear cached Redis client/provider so next access recreates fresh connections."""
    global _redis_client, _redis_signature
    global _redis_credential_provider, _redis_credential_provider_signature

    stale_client = _redis_client
    _redis_client = None
    _redis_signature = None
    if stale_client is not None:
        await _close_resource(stale_client)

    if reset_credential_provider:
        stale_provider = _redis_credential_provider
        _redis_credential_provider = None
        _redis_credential_provider_signature = None
        if stale_provider is not None:
            await _close_resource(stale_provider)


def _build_cluster_kwargs(common_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Build RedisCluster kwargs compatible with the installed redis-py version."""
    supported = inspect.signature(RedisCluster.__init__).parameters
    kwargs = dict(common_kwargs)
    if "cluster_error_retry_attempts" in supported:
        kwargs["cluster_error_retry_attempts"] = 3
    if "connection_error_retry_attempts" in supported:
        kwargs["connection_error_retry_attempts"] = 3
    if "dynamic_startup_nodes" in supported:
        # Keep bootstrap endpoint stable when shard nodes are not directly routable.
        kwargs["dynamic_startup_nodes"] = False
    return kwargs


def _should_use_cluster_address_remap(redis_host: str, redis_ssl: bool) -> bool:
    if not redis_ssl:
        return False
    host = redis_host.lower()
    return host.endswith(".redis.azure.net") or host.endswith(".redis.cache.windows.net")


def _cluster_address_remap_factory(redis_host: str, redis_port: int):
    def _address_remap(_address):
        # Route all cluster nodes through the configured TLS endpoint host/port.
        return redis_host, redis_port

    return _address_remap


def get_redis_client(settings_service: SettingsService):
    global _redis_client, _redis_signature
    cluster_enabled = _redis_cluster_enabled(settings_service)
    redis_host, redis_port = _get_redis_host_port(settings_service)
    redis_ssl = _get_redis_ssl(settings_service)
    signature = (
        redis_host,
        redis_port,
        settings_service.settings.redis_db,
        redis_ssl,
        cluster_enabled,
        _get_redis_entra_scope(settings_service),
        (settings_service.settings.redis_entra_object_id or "").strip(),
        settings_service.settings.redis_entra_refresh_margin_seconds,
    )
    if _redis_client is None or _redis_signature != signature:
        redis_credential_provider = get_redis_credential_provider(settings_service)
        common_kwargs = {
            "host": redis_host,
            "port": redis_port,
            "ssl": redis_ssl,
            "decode_responses": True,
            # Plain/local Redis (no Entra): fail fast so an absent Redis never stalls requests.
            "socket_connect_timeout": 5 if redis_credential_provider is not None else 2,
            "socket_timeout": 5 if redis_credential_provider is not None else 3,
            # Auto-detect stale connections before use
            "health_check_interval": 15,
            # Retry on transient connection drops (Azure idle timeout, etc.)
            "retry": Retry(ExponentialBackoff(cap=2, base=0.1), retries=3 if redis_credential_provider is not None else 1),
            "retry_on_error": [ConnectionError, TimeoutError, OSError],
        }
        if redis_credential_provider is not None:
            common_kwargs["credential_provider"] = redis_credential_provider
        elif (redis_password := _get_redis_password()) is not None:
            common_kwargs["password"] = redis_password
        if cluster_enabled:
            cluster_kwargs = _build_cluster_kwargs(common_kwargs)
            if (
                "address_remap" in inspect.signature(RedisCluster.__init__).parameters
                and _should_use_cluster_address_remap(redis_host, redis_ssl)
            ):
                cluster_kwargs["address_remap"] = _cluster_address_remap_factory(
                    redis_host, redis_port
                )
            _redis_client = RedisCluster(**cluster_kwargs)
        else:
            _redis_client = redis.StrictRedis(
                **common_kwargs,
                db=settings_service.settings.redis_db,
            )
        _redis_signature = signature
    return _redis_client
