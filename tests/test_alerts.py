from datetime import date

from app import alerts, db, metrics


def _insert_requests(day: str, total: int = 20, failures: int = 10) -> None:
    ts = f"{day}T10:00:00"
    rows = [
        (
            f"req-alert-{i}", ts, "tenant-001", "sk-tenant-001-demo",
            "deepseek-chat", "deepseek-chat", "prov_domestic", 10, 5, 0.0, 100,
            500 if i < failures else 200, "upstream_error" if i < failures else None,
            "direct", None, 0,
        )
        for i in range(total)
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


def test_compute_rules():
    kpis = {
        "requests": 100,
        "success_rate": 0.90,
        "rate_limited_ratio": 0.10,
        "p95_latency_ms": 3000,
        "cost": 100.0,
    }
    rules = {a["rule"] for a in alerts.compute("2026-10-30", kpis)}
    assert {"success_rate", "rate_limit", "p95_latency"} <= rules


def test_scan_persists_and_dedupes(fresh_db):
    day = date.today().isoformat()
    _insert_requests(day, total=20, failures=10)
    new_alerts = alerts.scan(day)
    assert len(new_alerts) >= 1
    count = db.query_one("SELECT COUNT(*) AS n FROM alerts WHERE rule = 'success_rate'")["n"]
    assert count == 1
    assert alerts.scan(day) == []
    count_again = db.query_one("SELECT COUNT(*) AS n FROM alerts WHERE rule = 'success_rate'")["n"]
    assert count_again == 1


def test_current_includes_persisted(fresh_db):
    day = date.today().isoformat()
    _insert_requests(day, total=20, failures=10)
    alerts.scan(day)
    current = alerts.current(day, metrics._kpis(day))
    assert any(a["rule"] == "success_rate" for a in current)
