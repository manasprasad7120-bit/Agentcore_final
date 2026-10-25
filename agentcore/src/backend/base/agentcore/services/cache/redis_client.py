import inspect
import os
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

    return True


def _get_redis_host_port(settings_service: SettingsService) -> tuple[str, int]:
    host = str(settings_service.settings.redis_host or "").strip().strip("'\"")
    if not host:
        msg = "REDIS_HOST must be set for Redis cache."
        raise ValueError(msg)

    raw_port = settings_service.settings.redis_port
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
    redis_entra_scope = (settings_service.settings.redis_entra_scope or "").strip()
    if not redis_entra_scope:
        msg = "REDIS_ENTRA_SCOPE must be set."
        raise ValueError(msg)
    return redis_entra_scope


def get_redis_credential_provider(settings_service: SettingsService) -> CredentialProvider:
    global _redis_credential_provider, _redis_credential_provider_signature

    redis_entra_scope = _get_redis_entra_scope(settings_service)
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
            "credential_provider": redis_credential_provider,
            "decode_responses": True,
            "socket_connect_timeout": 5,
            "socket_timeout": 5,
            # Auto-detect stale connections before use
            "health_check_interval": 15,
            # Retry on transient connection drops (Azure idle timeout, etc.)
            "retry": Retry(ExponentialBackoff(cap=2, base=0.1), retries=3),
            "retry_on_error": [ConnectionError, TimeoutError, OSError],
        }
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
