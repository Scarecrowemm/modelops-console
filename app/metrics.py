"""Dashboard and report queries."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from . import alerts, config, db, lifecycle, migration, pricing

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _date(value: str | None) -> str:
    if value and DATE_RE.match(value):
        return value
    return date.today().isoformat()


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = min(len(values) - 1, int(round(0.95 * (len(values) - 1))))
    return round(float(values[idx]), 1)


def _kpis(day: str) -> dict:
    row = db.query_one(
        """
        SELECT COUNT(*) AS requests,
               COALESCE(SUM(prompt_tokens + completion_tokens), 0) AS tokens,
               COALESCE(SUM(cost), 0) AS cost,
               COALESCE(SUM(CASE WHEN status_code = 200 THEN 1 ELSE 0 END), 0) AS ok,
               COALESCE(SUM(CASE WHEN status_code = 429 THEN 1 ELSE 0 END), 0) AS limited
        FROM requests WHERE ts LIKE ?
        """,
        (day + "%",),
    )
    requests = int(row["requests"] or 0)
    ok = int(row["ok"] or 0)
    limited = int(row["limited"] or 0)
    latencies = [
        float(r["latency_ms"])
        for r in db.query(
            "SELECT latency_ms FROM requests WHERE ts LIKE ? AND status_code = 200",
            (day + "%",),
        )
    ]
    return {
        "requests": requests,
        "tokens": int(row["tokens"] or 0),
        "cost": round(float(row["cost"] or 0), 4),
        "success_rate": round(ok / requests, 4) if requests else 0.0,
        "rate_limited_ratio": round(limited / requests, 4) if requests else 0.0,
        "p95_latency_ms": _p95(latencies),
    }


def _cost_trend(day: str) -> list[dict]:
    end = date.fromisoformat(day)
    days = [(end - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    rows = db.query(
        """
        SELECT substr(ts, 1, 10) AS day, ROUND(SUM(cost), 4) AS cost, COUNT(*) AS requests
        FROM requests WHERE substr(ts, 1, 10) >= ?
        GROUP BY day
        """,
        (days[0],),
    )
    by_day = {r["day"]: r for r in rows}
    return [
        {
            "day": d,
            "cost": float(by_day.get(d, {}).get("cost") or 0),
            "requests": int(by_day.get(d, {}).get("requests") or 0),
        }
        for d in days
    ]


def _cost_by_model(day: str) -> list[dict]:
    return db.query(
        """
        SELECT r.model_id, m.display_name, m.version, COUNT(*) AS requests,
               ROUND(SUM(r.cost), 4) AS cost
        FROM requests r JOIN models m ON m.id = r.model_id
        WHERE r.ts LIKE ?
        GROUP BY r.model_id
        ORDER BY cost DESC
        """,
        (day + "%",),
    )


def _top_tenants(day: str) -> list[dict]:
    return db.query(
        """
        SELECT r.tenant_id, t.name, t.tier, COUNT(*) AS requests,
               ROUND(SUM(r.cost), 4) AS cost
        FROM requests r JOIN tenants t ON t.id = r.tenant_id
        WHERE r.ts LIKE ?
        GROUP BY r.tenant_id
        ORDER BY cost DESC
        LIMIT 10
        """,
        (day + "%",),
    )


def _model_health(day: str) -> list[dict]:
    rows = db.query(
        """
        SELECT m.id, m.display_name, m.status, m.provider_id, m.canary_percent,
               COALESCE(r.requests, 0) AS requests,
               COALESCE(r.ok, 0) AS ok,
               COALESCE(r.cost, 0) AS cost
        FROM models m
        LEFT JOIN (
            SELECT model_id, COUNT(*) AS requests,
                   SUM(CASE WHEN status_code = 200 THEN 1 ELSE 0 END) AS ok,
                   SUM(cost) AS cost
            FROM requests WHERE ts LIKE ?
            GROUP BY model_id
        ) r ON r.model_id = m.id
        ORDER BY COALESCE(r.cost, 0) DESC
        """,
        (day + "%",),
    )
    lat_by_model: dict[str, list[float]] = {}
    for r in db.query(
        "SELECT model_id, latency_ms FROM requests WHERE ts LIKE ? AND status_code = 200",
        (day + "%",),
    ):
        lat_by_model.setdefault(r["model_id"], []).append(float(r["latency_ms"]))
    out = []
    for r in rows:
        requests = int(r["requests"] or 0)
        ok = int(r["ok"] or 0)
        out.append(
            {
                "model_id": r["id"],
                "display_name": r["display_name"],
                "status": r["status"],
                "provider_id": r["provider_id"],
                "canary_percent": float(r["canary_percent"] or 0),
                "requests": requests,
                "success_rate": round(ok / requests, 4) if requests else None,
                "p95_latency_ms": _p95(lat_by_model.get(r["id"], [])),
                "cost": round(float(r["cost"] or 0), 4),
            }
        )
    return out


def _alerts(day: str, kpis: dict) -> list[dict]:
    return alerts.current(day, kpis)


def dashboard(day: str | None = None) -> dict:
    day = _date(day)
    kpis = _kpis(day)
    return {
        "date": day,
        "kpis": kpis,
        "cost_trend": _cost_trend(day),
        "cost_by_model": _cost_by_model(day),
        "top_tenants": _top_tenants(day),
        "model_health": _model_health(day),
        "alerts": _alerts(day, kpis),
        "incidents": db.query(
            "SELECT id, ts, type, severity, summary, owner FROM incidents WHERE status = 'open' ORDER BY ts DESC"
        ),
        "lifecycle": lifecycle.board(),
        "migrations": migration.progress(),
        "upcoming_changes": pricing.upcoming_changes(),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
