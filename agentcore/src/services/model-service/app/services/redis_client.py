"""Build a Redis client for managed Azure Cache, mirroring the main backend.

Vendored from ``backend/base/agentcore/services/cache/redis_client.py`` so this
service connects to the same Redis instance the backend uses, via the same
Entra-token streaming credential provider. The two builders should agree on
config knobs; the source of truth lives in the backend.

Environment variables (unprefixed -- matches the backend's expectations):

  REDIS_HOST                          host name (required)
  REDIS_PORT                          port (required, integer)
  REDIS_DB                            db index (default 0)
  REDIS_SSL                           bool (default true; required for Azure)
  REDIS_ENTRA_SCOPE                   AAD scope, e.g. https://redis.azure.com/.default
  REDIS_ENTRA_OBJECT_ID               managed identity object id
  REDIS_ENTRA_REFRESH_MARGIN_SECONDS  token refresh margin (default 180)
  REDIS_CLUSTER_POLICY                enterprise|enterprisecluster|oss|osscluster
  REDIS_CLUSTER_ENABLED               bool fallback when policy is unset
"""

from __future__ import annotations

import inspect
import logging
import os
from typing import Any

import redis.asyncio as redis
from redis.asyncio.cluster import RedisCluster
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.services.redis_entra_credentials import AzureEntraRedisCredentialProvider

logger = logging.getLogger(__name__)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _cluster_enabled() -> bool:
    policy = (os.getenv("REDIS_CLUSTER_POLICY") or "").strip().lower()
    if policy in {"enterprise", "enterprisecluster"}:
        return False
    if policy in {"oss", "osscluster"}:
        return True
    # Default: cluster protocol only for Azure Managed Redis (Entra scope configured);
    # a plain/local Redis without Entra is a standalone server.
    entra_configured = bool((os.getenv("REDIS_ENTRA_SCOPE") or "").strip())
    return _bool_env("REDIS_CLUSTER_ENABLED", default=entra_configured)


def _should_remap_cluster_addresses(host: str, ssl: bool) -> bool:
    if not ssl:
        return False
    h = host.lower()
    return h.endswith(".redis.azure.net") or h.endswith(".redis.cache.windows.net")


def _cluster_address_remap_factory(host: str, port: int):
    def _remap(_address):  # noqa: ARG001 - matches redis-py callback signature
        return host, port

    return _remap


def _build_cluster_kwargs(common_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Filter ``common_kwargs`` to those supported by the installed RedisCluster."""
    supported = inspect.signature(RedisCluster.__init__).parameters
    kwargs = dict(common_kwargs)
    if "cluster_error_retry_attempts" in supported:
        kwargs["cluster_error_retry_attempts"] = 3
    if "connection_error_retry_attempts" in supported:
        kwargs["connection_error_retry_attempts"] = 3
    if "dynamic_startup_nodes" in supported:
        kwargs["dynamic_startup_nodes"] = False
    return kwargs


def is_redis_configured() -> bool:
    """Return True if the env has enough to attempt a Redis connection."""
    return bool((os.getenv("REDIS_HOST") or "").strip())


def build_redis_client():
    """Build an async Redis client (Cluster or StrictRedis) from env vars.

    Raises ``ValueError`` if required variables are missing -- callers should
    only invoke this after :func:`is_redis_configured` returns True.
    """
    host = (os.getenv("REDIS_HOST") or "").strip().strip("'\"")
    if not host:
        msg = "REDIS_HOST must be set to enable rate limiting."
        raise ValueError(msg)

    raw_port = os.getenv("REDIS_PORT")
    try:
        port = int(raw_port) if raw_port is not None else 0
    except ValueError as exc:
        msg = f"REDIS_PORT must be a valid integer. Got: {raw_port!r}"
        raise ValueError(msg) from exc
    if port <= 0:
        msg = f"REDIS_PORT must be > 0. Got: {port}"
        raise ValueError(msg)

    db = int(os.getenv("REDIS_DB", "0") or 0)
    ssl_enabled = _bool_env("REDIS_SSL", default=True)

    scope = (os.getenv("REDIS_ENTRA_SCOPE") or "").strip()
    auth_kwargs: dict[str, Any] = {}
    if scope:
        object_id = (os.getenv("REDIS_ENTRA_OBJECT_ID") or "").strip() or None
        refresh_margin = int(os.getenv("REDIS_ENTRA_REFRESH_MARGIN_SECONDS", "180") or 180)
        auth_kwargs["credential_provider"] = AzureEntraRedisCredentialProvider(
            scope=scope,
            object_id=object_id,
            refresh_margin_seconds=refresh_margin,
        )
    else:
        # Plain Redis without Entra ID (local demo / self-hosted): optional static password.
        password = (os.getenv("REDIS_PASSWORD") or "").strip()
        if password:
            auth_kwargs["password"] = password
        logger.info("REDIS_ENTRA_SCOPE not set; connecting to Redis without Entra ID authentication")

    common_kwargs: dict[str, Any] = {
        "host": host,
        "port": port,
        "ssl": ssl_enabled,
        **auth_kwargs,
        "decode_responses": True,
        "socket_connect_timeout": 5,
        "socket_timeout": 5,
        "health_check_interval": 15,
        "retry": Retry(ExponentialBackoff(cap=2, base=0.1), retries=3),
        "retry_on_error": [RedisConnectionError, RedisTimeoutError, OSError],
    }

    if _cluster_enabled():
        cluster_kwargs = _build_cluster_kwargs(common_kwargs)
        if (
            "address_remap" in inspect.signature(RedisCluster.__init__).parameters
            and _should_remap_cluster_addresses(host, ssl_enabled)
        ):
            cluster_kwargs["address_remap"] = _cluster_address_remap_factory(host, port)
        logger.info("Building RedisCluster client (host=%s port=%d ssl=%s)", host, port, ssl_enabled)
        return RedisCluster(**cluster_kwargs)

    logger.info("Building Redis StrictRedis client (host=%s port=%d ssl=%s db=%d)", host, port, ssl_enabled, db)
    return redis.StrictRedis(**common_kwargs, db=db)
