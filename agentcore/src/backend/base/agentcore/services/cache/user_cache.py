"""Redis-backed cache of user records.

Redis is optional: when it is not configured or unreachable the cache degrades to a
no-op (reads return None, writes are skipped) so authentication never blocks on it.
"""

from __future__ import annotations

import json

from loguru import logger
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError

from agentcore.services.cache.redis_client import (
    get_redis_client,
    mark_redis_down,
    mark_redis_up,
    redis_circuit_open,
    redis_configured,
)

_REDIS_ERRORS = (RedisConnectionError, RedisTimeoutError, RedisError, OSError)


class UserCacheService:
    def __init__(self, settings_service):
        self.ttl = settings_service.settings.redis_cache_expire or 3600
        self.redis = None
        if redis_configured(settings_service):
            try:
                self.redis = get_redis_client(settings_service)
            except Exception as exc:  # noqa: BLE001 - cache is optional
                logger.warning(f"User cache disabled (Redis client could not be created): {exc}")

    def _available(self) -> bool:
        return self.redis is not None and not redis_circuit_open()

    async def get_user(self, user_id: str):
        if not self._available():
            return None
        try:
            data = await self.redis.get(f"user:{user_id}")
        except _REDIS_ERRORS as exc:
            mark_redis_down(str(exc))
            logger.debug(f"User cache read skipped (Redis unavailable): {exc}")
            return None
        mark_redis_up()
        return json.loads(data) if data else None

    async def set_user(self, user_dict: dict):
        if not self._available():
            return
        key = f"user:{user_dict['id']}"
        try:
            await self.redis.setex(key, self.ttl, json.dumps(user_dict, default=str))
        except _REDIS_ERRORS as exc:
            mark_redis_down(str(exc))
            logger.debug(f"User cache write skipped (Redis unavailable): {exc}")

    async def delete_user(self, user_id: str):
        if not self._available():
            return
        try:
            await self.redis.delete(f"user:{user_id}")
        except _REDIS_ERRORS as exc:
            mark_redis_down(str(exc))
            logger.debug(f"User cache delete skipped (Redis unavailable): {exc}")
