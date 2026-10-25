import asyncio
import inspect
import os
import pickle
import threading
import time
from collections import OrderedDict
from typing import Generic, Union

import dill
from loguru import logger
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError
from typing_extensions import override

from agentcore.services.cache.base import (
    AsyncBaseCacheService,
    AsyncLockType,
    CacheService,
    ExternalAsyncBaseCacheService,
    LockType,
)
from agentcore.services.cache.utils import CACHE_MISS


class ThreadingInMemoryCache(CacheService, Generic[LockType]):
    """A simple in-memory cache using an OrderedDict.

    This cache supports setting a maximum size and expiration time for cached items.
    When the cache is full, it uses a Least Recently Used (LRU) eviction policy.
    Thread-safe using a threading Lock.

    Attributes:
        max_size (int, optional): Maximum number of items to store in the cache.
        expiration_time (int, optional): Time in seconds after which a cached item expires. Default is 1 hour.

    Example:
        cache = InMemoryCache(max_size=3, expiration_time=5)

        # setting cache values
        cache.set("a", 1)
        cache.set("b", 2)
        cache["c"] = 3

        # getting cache values
        a = cache.get("a")
        b = cache["b"]
    """

    def __init__(self, max_size=None, expiration_time=60 * 60) -> None:
        """Initialize a new InMemoryCache instance.

        Args:
            max_size (int, optional): Maximum number of items to store in the cache.
            expiration_time (int, optional): Time in seconds after which a cached item expires. Default is 1 hour.
        """
        self._cache: OrderedDict = OrderedDict()
        self._lock = threading.RLock()
        self.max_size = max_size
        self.expiration_time = expiration_time

    def get(self, key, lock: Union[threading.Lock, None] = None):  # noqa: UP007
        """Retrieve an item from the cache.

        Args:
            key: The key of the item to retrieve.
            lock: A lock to use for the operation.

        Returns:
            The value associated with the key, or CACHE_MISS if the key is not found or the item has expired.
        """
        with lock or self._lock:
            return self._get_without_lock(key)

    def _get_without_lock(self, key):
        """Retrieve an item from the cache without acquiring the lock."""
        if item := self._cache.get(key):
            if self.expiration_time is None or time.time() - item["time"] < self.expiration_time:
                # Move the key to the end to make it recently used
                self._cache.move_to_end(key)
                # Check if the value is pickled
                return pickle.loads(item["value"]) if isinstance(item["value"], bytes) else item["value"]
            self.delete(key)
        return CACHE_MISS

    def set(self, key, value, lock: Union[threading.Lock, None] = None) -> None:  # noqa: UP007
        """Add an item to the cache.

        If the cache is full, the least recently used item is evicted.

        Args:
            key: The key of the item.
            value: The value to cache.
            lock: A lock to use for the operation.
        """
        with lock or self._lock:
            if key in self._cache:
                # Remove existing key before re-inserting to update order
                self.delete(key)
            elif self.max_size and len(self._cache) >= self.max_size:
                # Remove least recently used item
                self._cache.popitem(last=False)
            # pickle locally to mimic Redis

            self._cache[key] = {"value": value, "time": time.time()}

    def upsert(self, key, value, lock: Union[threading.Lock, None] = None) -> None:  # noqa: UP007
        """Inserts or updates a value in the cache.

        If the existing value and the new value are both dictionaries, they are merged.

        Args:
            key: The key of the item.
            value: The value to insert or update.
            lock: A lock to use for the operation.
        """
        with lock or self._lock:
            existing_value = self._get_without_lock(key)
            if existing_value is not CACHE_MISS and isinstance(existing_value, dict) and isinstance(value, dict):
                existing_value.update(value)
                value = existing_value

            self.set(key, value)

    def get_or_set(self, key, value, lock: Union[threading.Lock, None] = None):  # noqa: UP007
        """Retrieve an item from the cache.

        If the item does not exist, set it with the provided value.

        Args:
            key: The key of the item.
            value: The value to cache if the item doesn't exist.
            lock: A lock to use for the operation.

        Returns:
            The cached value associated with the key.
        """
        with lock or self._lock:
            if key in self._cache:
                return self.get(key)
            self.set(key, value)
            return value

    def delete(self, key, lock: Union[threading.Lock, None] = None) -> None:  # noqa: UP007
        with lock or self._lock:
            self._cache.pop(key, None)

    def clear(self, lock: Union[threading.Lock, None] = None) -> None:  # noqa: UP007
        """Clear all items from the cache."""
        with lock or self._lock:
            self._cache.clear()

    def contains(self, key) -> bool:
        """Check if the key is in the cache."""
        return key in self._cache

    def __contains__(self, key) -> bool:
        """Check if the key is in the cache."""
        return self.contains(key)

    def __getitem__(self, key):
        """Retrieve an item from the cache using the square bracket notation."""
        return self.get(key)

    def __setitem__(self, key, value) -> None:
        """Add an item to the cache using the square bracket notation."""
        self.set(key, value)

    def __delitem__(self, key) -> None:
        """Remove an item from the cache using the square bracket notation."""
        self.delete(key)

    def __len__(self) -> int:
        """Return the number of items in the cache."""
        return len(self._cache)

    def __repr__(self) -> str:
        """Return a string representation of the InMemoryCache instance."""
        return f"InMemoryCache(max_size={self.max_size}, expiration_time={self.expiration_time})"


class RedisCache(ExternalAsyncBaseCacheService, Generic[LockType]):
    """A Redis-based cache implementation.

    This cache supports setting an expiration time for cached items.

    Attributes:
        expiration_time (int, optional): Time in seconds after which a cached item expires. Default is 1 hour.

    Example:
        cache = RedisCache(expiration_time=5)

        # setting cache values
        cache.set("a", 1)
        cache.set("b", 2)
        cache["c"] = 3

        # getting cache values
        a = cache.get("a")
        b = cache["b"]
    """

    def __init__(
        self,
        host=os.getenv("LOCALHOST_HOST", "localhost"),
        port=6379,
        db=0,
        credential_provider=None,
        cluster_enabled=True,
        ssl=False,
        expiration_time=60 * 60,
    ) -> None:
        """Initialize a new RedisCache instance.

        Args:
            host (str, optional): Redis host.
            port (int, optional): Redis port.
            db (int, optional): Redis DB.
            credential_provider (CredentialProvider): Redis credential provider.
            ssl (bool, optional): Use SSL connection.
            expiration_time (int, optional): Time in seconds after which a
                cached item expires. Default is 1 hour.
        """
        self._host = str(host).strip().strip("'\"")
        self._port = port
        self._db = db
        self._credential_provider = credential_provider
        self._cluster_enabled = cluster_enabled
        self._ssl = ssl

        # Redis is a main dependency, no need to import check
        from redis.asyncio import StrictRedis
        from redis.asyncio.cluster import RedisCluster
        from redis.asyncio.retry import Retry
        from redis.backoff import ExponentialBackoff

        # retry_on_timeout + Retry: when Redis restarts or a connection
        # goes stale, the client automatically drops the dead socket and
        # retries with a fresh connection — no server restart needed.
        _retry = Retry(ExponentialBackoff(), retries=3)
        if self._credential_provider is None:
            msg = "RedisCache requires an Entra ID credential provider."
            raise ValueError(msg)

        common_kwargs = {
            "host": self._host,
            "port": self._port,
            "ssl": self._ssl,
            "credential_provider": self._credential_provider,
            "socket_connect_timeout": 5,
            "socket_timeout": 5,
            "retry": _retry,
            "health_check_interval": 30,
        }
        if self._cluster_enabled:
            self._client = RedisCluster(**self._build_cluster_kwargs(common_kwargs))
        else:
            self._client = StrictRedis(
                **common_kwargs,
                db=self._db,
                retry_on_timeout=True,
            )
        self.expiration_time = expiration_time

    def _build_cluster_kwargs(self, common_kwargs: dict) -> dict:
        from redis.asyncio.cluster import RedisCluster

        supported = inspect.signature(RedisCluster.__init__).parameters
        kwargs = dict(common_kwargs)
        if "cluster_error_retry_attempts" in supported:
            kwargs["cluster_error_retry_attempts"] = 3
        if "connection_error_retry_attempts" in supported:
            kwargs["connection_error_retry_attempts"] = 3
        if "dynamic_startup_nodes" in supported:
            kwargs["dynamic_startup_nodes"] = False
        if (
            "address_remap" in supported
            and self._ssl
            and (
                self._host.lower().endswith(".redis.azure.net")
                or self._host.lower().endswith(".redis.cache.windows.net")
            )
        ):
            kwargs["address_remap"] = self._cluster_address_remap_factory()
        return kwargs

    def _cluster_address_remap_factory(self):
        def _address_remap(_address):
            # Route all cluster nodes through the configured TLS endpoint host/port.
            return self._host, self._port

        return _address_remap

    def _create_client(self):
        from redis.asyncio import StrictRedis
        from redis.asyncio.cluster import RedisCluster
        from redis.asyncio.retry import Retry
        from redis.backoff import ExponentialBackoff

        _retry = Retry(ExponentialBackoff(), retries=3)
        common_kwargs = {
            "host": self._host,
            "port": self._port,
            "ssl": self._ssl,
            "credential_provider": self._credential_provider,
            "socket_connect_timeout": 5,
            "socket_timeout": 5,
            "retry": _retry,
            "health_check_interval": 30,
        }
        if self._cluster_enabled:
            return RedisCluster(**self._build_cluster_kwargs(common_kwargs))
        return StrictRedis(
            **common_kwargs,
            db=self._db,
            retry_on_timeout=True,
        )

    async def _close_client(self, client) -> None:
        close_fn = getattr(client, "aclose", None) or getattr(client, "close", None)
        if not callable(close_fn):
            return
        try:
            result = close_fn()
            if inspect.isawaitable(result):
                await result
        except Exception:
            return

    async def _reconnect_client(self) -> None:
        # Force a token refresh before creating a new client so cluster
        # discovery doesn't fail with an expired Entra token.
        if self._credential_provider is not None:
            refresh = getattr(self._credential_provider, "_get_or_refresh_token", None)
            if callable(refresh):
                try:
                    refresh(force_refresh=True)
                except Exception:
                    pass  # best-effort; the new client will retry on its own
        stale_client = self._client
        self._client = self._create_client()
        await self._close_client(stale_client)

    async def _run_with_reconnect(self, *, operation: str, call):
        try:
            return await call(self._client)
        except (RedisConnectionError, RedisTimeoutError, RedisError, OSError) as exc:
            logger.warning(
                f"RedisCache {operation} failed: {exc}. "
                "Reconnecting Redis client and retrying once."
            )
            try:
                await self._reconnect_client()
                return await call(self._client)
            except (RedisConnectionError, RedisTimeoutError, RedisError, OSError) as retry_exc:
                logger.error(
                    f"RedisCache {operation} failed after reconnect: {retry_exc}"
                )
                raise

    async def is_connected(self) -> bool:
        """Check if the Redis client is connected."""
        try:
            await self._run_with_reconnect(
                operation="ping",
                call=lambda client: client.ping(),
            )
        except (RedisConnectionError, RedisTimeoutError, RedisError, OSError) as exc:
            logger.warning(f"RedisCache connection check failed: {exc}")
            return False
        return True

    @override
    async def get(self, key, lock=None):
        if key is None:
            return CACHE_MISS
        value = await self._run_with_reconnect(
            operation="get",
            call=lambda client: client.get(str(key)),
        )
        return dill.loads(value) if value else CACHE_MISS

    @override
    async def set(self, key, value, lock=None) -> None:
        try:
            if pickled := dill.dumps(value, recurse=True):
                result = await self._run_with_reconnect(
                    operation="setex",
                    call=lambda client: client.setex(str(key), self.expiration_time, pickled),
                )
                if not result:
                    msg = "RedisCache could not set the value."
                    raise ValueError(msg)
        except pickle.PicklingError as exc:
            msg = "RedisCache only accepts values that can be pickled. "
            raise TypeError(msg) from exc

    @override
    async def upsert(self, key, value, lock=None) -> None:
        """Inserts or updates a value in the cache.

        If the existing value and the new value are both dictionaries, they are merged.

        Args:
            key: The key of the item.
            value: The value to insert or update.
            lock: A lock to use for the operation.
        """
        if key is None:
            return
        existing_value = await self.get(key)
        if existing_value is not None and isinstance(existing_value, dict) and isinstance(value, dict):
            existing_value.update(value)
            value = existing_value

        await self.set(key, value)

    @override
    async def delete(self, key, lock=None) -> None:
        await self._run_with_reconnect(
            operation="delete",
            call=lambda client: client.delete(key),
        )

    @override
    async def clear(self, lock=None) -> None:
        """Clear all items from the cache."""
        await self._run_with_reconnect(
            operation="flushdb",
            call=lambda client: client.flushdb(),
        )

    async def contains(self, key) -> bool:
        """Check if the key is in the cache."""
        if key is None:
            return False
        value = await self._run_with_reconnect(
            operation="exists",
            call=lambda client: client.exists(str(key)),
        )
        return bool(value)

    def __repr__(self) -> str:
        """Return a string representation of the RedisCache instance."""
        return f"RedisCache(expiration_time={self.expiration_time})"

    async def teardown(self) -> None:
        await self._close_client(self._client)
        
class AsyncInMemoryCache(AsyncBaseCacheService, Generic[AsyncLockType]):
    def __init__(self, max_size=None, expiration_time=3600) -> None:
        self.cache: OrderedDict = OrderedDict()

        self.lock = asyncio.Lock()
        self.max_size = max_size
        self.expiration_time = expiration_time

    async def get(self, key, lock: asyncio.Lock | None = None):
        async with lock or self.lock:
            return await self._get(key)

    async def _get(self, key):
        item = self.cache.get(key, None)
        if item:
            if time.time() - item["time"] < self.expiration_time:
                self.cache.move_to_end(key)
                return pickle.loads(item["value"]) if isinstance(item["value"], bytes) else item["value"]
            logger.info(f"Cache item for key '{key}' has expired and will be deleted.")
            await self._delete(key)  # Log before deleting the expired item
        return CACHE_MISS

    async def set(self, key, value, lock: asyncio.Lock | None = None) -> None:
        async with lock or self.lock:
            await self._set(
                key,
                value,
            )

    async def _set(self, key, value) -> None:
        if self.max_size and len(self.cache) >= self.max_size:
            self.cache.popitem(last=False)
        self.cache[key] = {"value": value, "time": time.time()}
        self.cache.move_to_end(key)

    async def delete(self, key, lock: asyncio.Lock | None = None) -> None:
        async with lock or self.lock:
            await self._delete(key)

    async def _delete(self, key) -> None:
        if key in self.cache:
            del self.cache[key]

    async def clear(self, lock: asyncio.Lock | None = None) -> None:
        async with lock or self.lock:
            await self._clear()

    async def _clear(self) -> None:
        self.cache.clear()

    async def upsert(self, key, value, lock: asyncio.Lock | None = None) -> None:
        await self._upsert(key, value, lock)

    async def _upsert(self, key, value, lock: asyncio.Lock | None = None) -> None:
        existing_value = await self.get(key, lock)
        if existing_value is not None and isinstance(existing_value, dict) and isinstance(value, dict):
            existing_value.update(value)
            value = existing_value
        await self.set(key, value, lock)

    async def contains(self, key) -> bool:
        return key in self.cache
