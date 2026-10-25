"""Rate limiter for MiBuddy services.

Thread-safe, in-memory rate limiter using sliding window algorithm.
Tracks requests per user and enforces configurable limits.

Used for:
- Image generation (prevent abuse of DALL-E / Nano Banana APIs)
- Can be reused for any per-user rate limiting need
"""

from __future__ import annotations

import time
import threading
from collections import defaultdict, deque

import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    """Thread-safe rate limiter using sliding window algorithm."""

    def __init__(self, max_requests: int = 10, time_window: int = 3600):
        """Initialize the rate limiter.

        Args:
            max_requests: Maximum requests allowed per time window.
            time_window: Time window in seconds (default: 3600 = 1 hour).
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.user_requests: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()
        logger.info(f"[RateLimiter] Initialized: {max_requests} requests per {time_window}s")

    def _cleanup_expired(self, user_id: str, current_time: float) -> None:
        cutoff = current_time - self.time_window
        while self.user_requests[user_id] and self.user_requests[user_id][0] < cutoff:
            self.user_requests[user_id].popleft()
        if not self.user_requests[user_id]:
            del self.user_requests[user_id]

    def check(self, user_id: str) -> tuple[bool, int | None]:
        """Check if a user can make a request.

        Returns:
            (allowed, seconds_until_reset)
            - allowed: True if request is allowed
            - seconds_until_reset: seconds until limit resets (None if allowed)
        """
        with self.lock:
            now = time.time()
            if user_id in self.user_requests:
                self._cleanup_expired(user_id, now)

            count = len(self.user_requests.get(user_id, []))
            if count >= self.max_requests:
                oldest = self.user_requests[user_id][0]
                reset_in = int(self.time_window - (now - oldest)) + 1
                logger.warning(f"[RateLimiter] Rate limit exceeded for user {user_id}: {count}/{self.max_requests}, reset in {reset_in}s")
                return False, reset_in

            return True, None

    def record(self, user_id: str) -> None:
        """Record a successful request for a user."""
        with self.lock:
            self.user_requests[user_id].append(time.time())

    def remaining(self, user_id: str) -> int:
        """Get remaining requests for a user."""
        with self.lock:
            now = time.time()
            if user_id in self.user_requests:
                self._cleanup_expired(user_id, now)
            count = len(self.user_requests.get(user_id, []))
            return max(0, self.max_requests - count)


# ---------------------------------------------------------------------------
# Global image generation rate limiter instance
# ---------------------------------------------------------------------------

# Configurable via settings, but defaults to 10 requests per hour
_image_rate_limiter: RateLimiter | None = None


def get_image_rate_limiter() -> RateLimiter:
    """Get or create the global image generation rate limiter."""
    global _image_rate_limiter
    if _image_rate_limiter is None:
        try:
            from agentcore.services.deps import get_settings_service
            settings = get_settings_service().settings
            max_req = getattr(settings, "image_gen_rate_limit", 10)
            window = getattr(settings, "image_gen_rate_window", 3600)
        except Exception:
            max_req = 10
            window = 3600
        _image_rate_limiter = RateLimiter(max_requests=max_req, time_window=window)
    return _image_rate_limiter
