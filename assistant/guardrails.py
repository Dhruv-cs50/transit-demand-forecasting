"""In-memory guardrails for ``/chat``: a per-IP rate limiter and a routing cache.

Both are per Cloud Run instance (the spec accepts that at two instances; no
Redis), both take an injectable clock so tests never sleep, and both are
bounded so a flood of distinct keys cannot grow memory without limit.
"""

from __future__ import annotations

import math
import time
from collections import deque
from typing import Any, Callable

# Above this many tracked clients, drop the ones whose window has fully expired.
MAX_TRACKED_IPS = 10_000
MAX_CACHE_ENTRIES = 512


class RateLimiter:
    """Sliding window: at most ``limit`` allowed calls per ``window_s`` per ``ip``.

    A refused call is not recorded, so being refused never extends the wait.
    """

    def __init__(self, limit: int, window_s: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._limit = limit
        self._window = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def allow(self, ip: str) -> bool:
        now = self._clock()
        hits = self._hits.get(ip)
        if hits is None:
            self._sweep(now)
            hits = self._hits.setdefault(ip, deque())
        while hits and now - hits[0] >= self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True

    def retry_after_s(self, ip: str) -> int:
        """Whole seconds until ``ip`` may ask again (at least 1)."""
        hits = self._hits.get(ip)
        if not hits or len(hits) < self._limit:
            return 1
        return max(1, math.ceil(self._window - (self._clock() - hits[0])))

    def _sweep(self, now: float) -> None:
        if len(self._hits) < MAX_TRACKED_IPS:
            return
        stale = [ip for ip, hits in self._hits.items() if not hits or now - hits[-1] >= self._window]
        for ip in stale:
            del self._hits[ip]


class RoutingCache:
    """Entries live ``ttl_s`` seconds; the oldest go first when ``max_entries`` is hit."""

    def __init__(
        self,
        ttl_s: int,
        max_entries: int = MAX_CACHE_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_s
        self._max = max_entries
        self._clock = clock
        self._items: dict[Any, tuple[float, Any]] = {}

    def get(self, key: Any) -> Any | None:
        hit = self._items.get(key)
        if hit is None:
            return None
        stored_at, value = hit
        if self._clock() - stored_at >= self._ttl:
            del self._items[key]
            return None
        return value

    def set(self, key: Any, value: Any) -> None:
        self._items.pop(key, None)
        self._items[key] = (self._clock(), value)
        while len(self._items) > self._max:
            del self._items[next(iter(self._items))]  # dicts keep insertion order: the oldest

    def __len__(self) -> int:
        return len(self._items)
