from app import db
from scripts import replay


def test_replay_cost_reconciles(fresh_db):
    rows = replay.build_rows(100, 1)
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
    result = replay.reconcile()
    assert result["rows"] > 50
    assert result["total_diff_pct"] < 1.0
    assert result["rows_over_1_cent"] == 0
