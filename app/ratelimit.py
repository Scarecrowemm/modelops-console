"""Per-tenant RPM/TPM limiter (one-minute fixed window).

The limiter is intentionally in-memory: this is an operations demo, not a
distributed gateway. The README documents how to replace it with Redis.
"""

from __future__ import annotations

import os
import threading
import time
from typing import NamedTuple


class Decision(NamedTuple):
    allowed: bool
    reason: str | None
    retry_after: int


class RateLimiter:
    def __init__(self) -> None:
        self._state: dict[str, dict] = {}
        self._lock = threading.Lock()

    def check(
        self,
        tenant_id: str,
        rpm_limit: int,
        tpm_limit: int,
        estimated_tokens: int,
    ) -> Decision:
        now = int(time.time())
        window = now // 60
        with self._lock:
            s = self._state.setdefault(tenant_id, {"window": window, "rpm": 0, "tpm": 0})
            if s["window"] != window:
                s.update(window=window, rpm=0, tpm=0)
            if s["rpm"] + 1 > rpm_limit:
                return Decision(False, "rpm_exceeded", 60 - now % 60)
            if s["tpm"] + estimated_tokens > tpm_limit:
                return Decision(False, "tpm_exceeded", 60 - now % 60)
            s["rpm"] += 1
            s["tpm"] += estimated_tokens
            return Decision(True, None, 0)

    def adjust(self, tenant_id: str, delta: int) -> None:
        """Correct the token estimate with actual usage (can be negative)."""
        with self._lock:
            s = self._state.get(tenant_id)
            if s:
                s["tpm"] = max(0, s["tpm"] + delta)

    def reset(self) -> None:
        with self._lock:
            self._state.clear()

    def snapshot(self, tenant_id: str) -> dict:
        with self._lock:
            return dict(self._state.get(tenant_id, {}))


def get_limiter():
    url = os.getenv("MODELOPS_REDIS_URL", "").strip()
    if url:
        from .ratelimit_redis import RedisRateLimiter

        return RedisRateLimiter(url)
    return RateLimiter()


limiter = get_limiter()
