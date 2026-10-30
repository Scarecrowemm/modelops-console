"""Optional Redis-backed limiter.

Enabled by setting MODELOPS_REDIS_URL. If the `redis` package is missing or the
server is unreachable, it transparently falls back to the in-process limiter so
the demo still runs.
"""

from __future__ import annotations

import time

from .ratelimit import Decision, RateLimiter

try:  # optional dependency
    import redis
except ImportError:  # pragma: no cover - exercised only when redis is absent
    redis = None


class RedisRateLimiter:
    def __init__(self, url: str, fallback: RateLimiter | None = None):
        self._fallback = fallback or RateLimiter()
        self._client = None
        if redis is None:
            return
        try:
            self._client = redis.Redis.from_url(
                url, socket_connect_timeout=0.3, socket_timeout=0.3, decode_responses=True
            )
            self._client.ping()
        except Exception:
            self._client = None

    @property
    def using_redis(self) -> bool:
        return self._client is not None

    def check(self, tenant_id: str, rpm_limit: int, tpm_limit: int, estimated_tokens: int) -> Decision:
        if self._client is None:
            return self._fallback.check(tenant_id, rpm_limit, tpm_limit, estimated_tokens)
        window = int(time.time()) // 60
        rpm_key = f"rl:{tenant_id}:rpm:{window}"
        tpm_key = f"rl:{tenant_id}:tpm:{window}"
        try:
            pipe = self._client.pipeline()
            pipe.incr(rpm_key)
            pipe.expire(rpm_key, 120)
            pipe.incrby(tpm_key, estimated_tokens)
            pipe.expire(tpm_key, 120)
            rpm, _, tpm, _ = pipe.execute()
            retry_after = 60 - int(time.time()) % 60
            if int(rpm) > rpm_limit:
                return Decision(False, "rpm_exceeded", retry_after)
            if int(tpm) > tpm_limit:
                return Decision(False, "tpm_exceeded", retry_after)
            return Decision(True, None, 0)
        except Exception:
            return self._fallback.check(tenant_id, rpm_limit, tpm_limit, estimated_tokens)

    def adjust(self, tenant_id: str, delta: int) -> None:
        if self._client is None:
            self._fallback.adjust(tenant_id, delta)
            return
        try:
            window = int(time.time()) // 60
            self._client.incrby(f"rl:{tenant_id}:tpm:{window}", delta)
        except Exception:
            self._fallback.adjust(tenant_id, delta)

    def reset(self) -> None:
        self._fallback.reset()
