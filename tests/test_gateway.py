import pytest

from app import db, providers, ratelimit

HEADERS = {"Authorization": "Bearer sk-tenant-001-demo"}
BODY = {"model": "deepseek-chat", "messages": [{"role": "user", "content": "你好"}]}


def fake_ok(model, messages, max_tokens=256, latency_scale=1.0, force_failure=None):
    return providers.ProviderResult(
        text="ok", prompt_tokens=10, completion_tokens=5, latency_ms=5,
        model_id=model["id"], provider_id=model["provider_id"],
    )


@pytest.fixture(autouse=True)
def _reset_limiter(fresh_db):
    ratelimit.limiter.reset()
    db.execute("UPDATE models SET canary_percent = 0 WHERE id = 'deepseek-chat-v3'")
    yield


def test_missing_key_returns_401(client):
    r = client.post("/v1/chat/completions", json=BODY)
    assert r.status_code == 401
    assert r.json()["error"]["type"] == "missing_api_key"


def test_invalid_key_returns_401(client):
    r = client.post("/v1/chat/completions", headers={"Authorization": "Bearer nope"}, json=BODY)
    assert r.status_code == 401


def test_success_meters_cost_and_logs(client, monkeypatch):
    monkeypatch.setattr(providers, "call", fake_ok)
    r = client.post("/v1/chat/completions", headers=HEADERS, json=BODY)
    assert r.status_code == 200
    body = r.json()
    assert body["usage"]["total_tokens"] == 15
    assert r.headers["X-Model"] == "deepseek-chat"
    assert float(r.headers["X-Cost"]) == pytest.approx(0.0028, abs=1e-6)
    row = db.query_one("SELECT * FROM requests ORDER BY rowid DESC LIMIT 1")
    assert row["status_code"] == 200
    assert row["route_reason"] == "direct"


def test_migration_route_uses_canary_model(client, monkeypatch):
    monkeypatch.setattr(providers, "call", fake_ok)
    headers = {"Authorization": "Bearer sk-tenant-003-demo"}
    r = client.post("/v1/chat/completions", headers=headers, json=BODY)
    assert r.status_code == 200
    assert r.headers["X-Model"] == "deepseek-chat-v3"
    assert r.headers["X-Route-Reason"] == "migration"


def test_canary_percentage_routes_to_v3(client, monkeypatch):
    db.execute("UPDATE models SET canary_percent = 1.0 WHERE id = 'deepseek-chat-v3'")
    monkeypatch.setattr(providers, "call", fake_ok)
    r = client.post("/v1/chat/completions", headers=HEADERS, json=BODY)
    assert r.status_code == 200
    assert r.headers["X-Model"] == "deepseek-chat-v3"
    assert r.headers["X-Route-Reason"] == "canary"
    assert r.headers["X-Fallback-From"] == "deepseek-chat"


def test_canary_model_cannot_be_called_directly(client):
    body = {"model": "deepseek-chat-v3", "messages": [{"role": "user", "content": "hi"}]}
    r = client.post("/v1/chat/completions", headers=HEADERS, json=body)
    assert r.status_code == 409
    assert r.json()["error"]["type"] == "model_in_canary"


def test_fallback_on_upstream_error(client, monkeypatch):
    def fake(model, messages, max_tokens=256, latency_scale=1.0, force_failure=None):
        if model["id"] == "deepseek-chat":
            raise providers.ProviderError("429")
        return providers.ProviderResult(
            text="fallback", prompt_tokens=10, completion_tokens=5, latency_ms=5,
            model_id=model["id"], provider_id=model["provider_id"],
        )

    monkeypatch.setattr(providers, "call", fake)
    r = client.post("/v1/chat/completions", headers=HEADERS, json=BODY)
    assert r.status_code == 200
    assert r.headers["X-Model"] == "qwen-plus"
    assert r.headers["X-Route-Reason"] == "fallback"
    assert r.headers["X-Fallback-From"] == "deepseek-chat"


def test_tenant_rate_limit_returns_429(client, monkeypatch):
    monkeypatch.setattr(providers, "call", fake_ok)
    headers = {"Authorization": "Bearer sk-tenant-181-demo"}  # free tier: 20 RPM
    for _ in range(20):
        assert client.post("/v1/chat/completions", headers=headers, json=BODY).status_code == 200
    r = client.post("/v1/chat/completions", headers=headers, json=BODY)
    assert r.status_code == 429
    assert r.json()["error"]["type"] == "rpm_exceeded"
    assert "Retry-After" in r.headers
