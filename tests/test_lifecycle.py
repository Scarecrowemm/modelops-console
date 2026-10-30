from datetime import datetime

import pytest

from app import db, lifecycle, migration


def _insert_v3_success(n: int = 25) -> None:
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    rows = [
        (
            f"req-v3-{i}", now, "tenant-003", "sk-tenant-003-demo", "deepseek-chat",
            "deepseek-chat-v3", "prov_domestic", 10, 5, 0.003, 400, 200, None,
            "migration", "deepseek-chat", 0,
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


def test_invalid_transition_rejected(fresh_db):
    with pytest.raises(lifecycle.LifecycleError):
        lifecycle.transition("deepseek-chat-v3", "offline", "skip steps")


def test_canary_to_active_requires_traffic(fresh_db):
    with pytest.raises(lifecycle.LifecycleError) as exc:
        lifecycle.transition("deepseek-chat-v3", "active", "no traffic yet")
    assert "门槛" in str(exc.value)


def test_canary_to_active_with_traffic(fresh_db):
    _insert_v3_success(25)
    result = lifecycle.transition("deepseek-chat-v3", "active", "7 天观察通过")
    assert result["to"] == "active"
    assert lifecycle.get_model("deepseek-chat-v3")["status"] == "active"


def test_active_to_deprecating_requires_migration_plan(fresh_db):
    result = lifecycle.transition("deepseek-chat", "deprecating", "下月涨价")
    assert result["to"] == "deprecating"


def test_offline_requires_migration_completion(fresh_db):
    lifecycle.transition("deepseek-chat", "deprecating", "x")
    with pytest.raises(lifecycle.LifecycleError):
        lifecycle.transition("deepseek-chat", "offline", "too early")
    for batch in ("5%", "20%", "50%", "100%"):
        migration.complete_batch(batch, from_model="deepseek-chat")
    result = lifecycle.transition("deepseek-chat", "offline", "迁移完成")
    assert result["to"] == "offline"
