from app.ratelimit import RateLimiter


def test_rpm_limit():
    rl = RateLimiter()
    assert rl.check("t1", rpm_limit=2, tpm_limit=10000, estimated_tokens=10).allowed
    assert rl.check("t1", rpm_limit=2, tpm_limit=10000, estimated_tokens=10).allowed
    d = rl.check("t1", rpm_limit=2, tpm_limit=10000, estimated_tokens=10)
    assert not d.allowed
    assert d.reason == "rpm_exceeded"
    assert d.retry_after > 0


def test_tpm_limit():
    rl = RateLimiter()
    assert rl.check("t2", rpm_limit=100, tpm_limit=100, estimated_tokens=60).allowed
    d = rl.check("t2", rpm_limit=100, tpm_limit=100, estimated_tokens=60)
    assert not d.allowed
    assert d.reason == "tpm_exceeded"


def test_adjust_can_free_budget():
    rl = RateLimiter()
    assert rl.check("t3", rpm_limit=100, tpm_limit=100, estimated_tokens=80).allowed
    rl.adjust("t3", -70)  # actual usage was much lower than the estimate
    assert rl.check("t3", rpm_limit=100, tpm_limit=100, estimated_tokens=60).allowed
