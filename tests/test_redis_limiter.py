from app.ratelimit import RateLimiter
from app.ratelimit_redis import RedisRateLimiter


def test_redis_limiter_falls_back_when_unreachable():
    local = RateLimiter()
    limiter = RedisRateLimiter("redis://127.0.0.1:6399", fallback=local)
    # No Redis on 6399: calls must still work through the in-process fallback.
    assert limiter.using_redis is False
    assert limiter.check("t1", rpm_limit=2, tpm_limit=1000, estimated_tokens=10).allowed
    assert limiter.check("t1", rpm_limit=2, tpm_limit=1000, estimated_tokens=10).allowed
    decision = limiter.check("t1", rpm_limit=2, tpm_limit=1000, estimated_tokens=10)
    assert decision.allowed is False
    assert decision.reason == "rpm_exceeded"
