"""Synchronous token-bucket rate limiter (sleep outside lock)."""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


class TokenBucketLimiter:
    def __init__(self, *, rate: float, burst: float) -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        if burst <= 0:
            raise ValueError("burst must be > 0")
        self._rate = float(rate)
        self._burst = float(burst)
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire_sync(self) -> None:
        while True:
            wait_for: Optional[float] = None
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
                self._last_refill = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait_for = (1.0 - self._tokens) / self._rate
            if wait_for is not None and wait_for > 0:
                logger.debug("rate_limiter_throttle wait=%.3fs", wait_for)
                time.sleep(wait_for)
