from datetime import datetime

from app import db
from scripts import canary_check


def _insert(model_id: str, n: int, errors: int = 0, latency: int = 400) -> None:
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    rows = [
        (
            f"req-{model_id}-{i}", now, "tenant-001", "sk-tenant-001-demo",
            "deepseek-chat", model_id, "prov_domestic", 10, 5, 0.003, latency,
            500 if i < errors else 200, None if i >= errors else "upstream_error",
            "canary", "deepseek-chat", 0,
        )
        for i in range(n)
    ]
    db.executemany(
        """
        INSERT INTO requests (
            request_id, ts, tenant_id, key_id, requested_model, model_id, provider_id,
            prompt_tokens, completion_tokens, cost, latency_ms, status_code, error_type,
            route_reason, fallback_from, cached
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )


def test_wait_when_insufficient_traffic(fresh_db):
    db.execute("UPDATE models SET canary_percent = 0.10 WHERE id = 'deepseek-chat-v3'")
    _insert("deepseek-chat-v3", 10)
    result = canary_check.check()[0]
    assert result["action"] == "wait"


def test_rollback_on_error_rate(fresh_db):
    db.execute("UPDATE models SET canary_percent = 0.10 WHERE id = 'deepseek-chat-v3'")
    _insert("deepseek-chat-v3", 30, errors=2)
    result = canary_check.check()[0]
    assert result["action"] == "rollback"
    model = db.query_one("SELECT * FROM models WHERE id = 'deepseek-chat-v3'")
    assert model["status"] == "rolled_back"
    assert model["canary_percent"] == 0


def test_promote_when_healthy(fresh_db):
    db.execute("UPDATE models SET canary_percent = 0.10 WHERE id = 'deepseek-chat-v3'")
    _insert("deepseek-chat-v3", 30, errors=0, latency=400)
    _insert("deepseek-chat", 30, errors=0, latency=500)
    result = canary_check.check()[0]
    assert result["action"] == "promote"
    assert result["new_percent"] == 0.25
    model = db.query_one("SELECT * FROM models WHERE id = 'deepseek-chat-v3'")
    assert model["canary_percent"] == 0.25
