"""Canary health check: promote or roll back based on the last 24 hours.

Usage:
    python scripts/canary_check.py
    python scripts/canary_check.py --dry-run

Rules:
- fewer than 20 requests in 24h -> keep waiting
- error rate > 2% or P95 > 1.5x incumbent -> roll back (percent = 0, status = rolled_back)
- otherwise promote by +15 percentage points, capped at 50%
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402

MIN_REQUESTS = 20
MAX_ERROR_RATE = 0.02
MAX_P95_RATIO = 1.5
PROMOTE_STEP = 0.15
MAX_PERCENT = 0.50


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return float(values[min(len(values) - 1, int(round(0.95 * (len(values) - 1))))])


def check(dry_run: bool = False) -> list[dict]:
    since = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
    canaries = db.query("SELECT * FROM models WHERE status = 'canary' AND canary_percent > 0")
    results = []
    for c in canaries:
        incumbent = db.query_one(
            """
            SELECT * FROM models
            WHERE status = 'active' AND provider_id = ? AND id != ?
            ORDER BY quality_score DESC LIMIT 1
            """,
            (c["provider_id"], c["id"]),
        )
        row = db.query_one(
            """
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(CASE WHEN status_code = 200 THEN 1 ELSE 0 END), 0) AS ok
            FROM requests WHERE model_id = ? AND ts >= ?
            """,
            (c["id"], since),
        )
        total = int(row["total"] or 0)
        ok = int(row["ok"] or 0)
        error_rate = 0.0 if total == 0 else 1 - ok / total
        canary_lat = [
            float(r["latency_ms"])
            for r in db.query(
                "SELECT latency_ms FROM requests WHERE model_id = ? AND ts >= ? AND status_code = 200",
                (c["id"], since),
            )
        ]
        inc_lat = []
        if incumbent:
            inc_lat = [
                float(r["latency_ms"])
                for r in db.query(
                    "SELECT latency_ms FROM requests WHERE model_id = ? AND ts >= ? AND status_code = 200",
                    (incumbent["id"], since),
                )
            ]
        canary_p95 = _p95(canary_lat)
        inc_p95 = _p95(inc_lat)
        result = {
            "model_id": c["id"],
            "requests": total,
            "error_rate": round(error_rate, 4),
            "p95_latency_ms": canary_p95,
            "incumbent": incumbent["id"] if incumbent else None,
            "incumbent_p95_ms": inc_p95,
            "before_percent": float(c["canary_percent"]),
        }

        if total < MIN_REQUESTS:
            result.update(action="wait", reason=f"only {total} requests (need {MIN_REQUESTS})")
        elif error_rate > MAX_ERROR_RATE:
            result.update(action="rollback", reason=f"error rate {error_rate:.2%} > {MAX_ERROR_RATE:.0%}")
        elif inc_p95 and canary_p95 > inc_p95 * MAX_P95_RATIO:
            result.update(action="rollback", reason=f"P95 {canary_p95:.0f}ms > {MAX_P95_RATIO}x incumbent {inc_p95:.0f}ms")
        elif float(c["canary_percent"]) >= MAX_PERCENT:
            result.update(action="keep", reason="already at 50%")
        else:
            new_percent = min(MAX_PERCENT, float(c["canary_percent"]) + PROMOTE_STEP)
            result.update(action="promote", new_percent=new_percent, reason="healthy")

        if not dry_run and result["action"] == "rollback":
            db.execute(
                "UPDATE models SET status = 'rolled_back', canary_percent = 0 WHERE id = ?",
                (c["id"],),
            )
            db.execute(
                "INSERT INTO lifecycle_events (model_id, from_status, to_status, reason, actor, ts) VALUES (?,?,?,?,?,?)",
                (c["id"], "canary", "rolled_back", result["reason"], "canary-check",
                 datetime.now().strftime("%Y-%m-%dT%H:%M:%S")),
            )
        elif not dry_run and result["action"] == "promote":
            db.execute(
                "UPDATE models SET canary_percent = ? WHERE id = ?",
                (result["new_percent"], c["id"]),
            )
            db.execute(
                "INSERT INTO lifecycle_events (model_id, from_status, to_status, reason, actor, ts) VALUES (?,?,?,?,?,?)",
                (c["id"], "canary", "canary",
                 f"灰度比例 {result['before_percent']:.0%} → {result['new_percent']:.0%}",
                 "canary-check", datetime.now().strftime("%Y-%m-%dT%H:%M:%S")),
            )
        results.append(result)
    return results


def main() -> int:
    db.init_db()
    dry_run = "--dry-run" in sys.argv
    results = check(dry_run=dry_run)
    if not results:
        print("no canary models with canary_percent > 0")
        return 0
    for r in results:
        print(
            f"{r['model_id']}: {r['requests']} req, error {r['error_rate']:.2%}, "
            f"P95 {r['p95_latency_ms']:.0f}ms vs {r['incumbent']} {r['incumbent_p95_ms']:.0f}ms "
            f"-> {r['action']} ({r['reason']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
