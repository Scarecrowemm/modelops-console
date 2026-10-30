"""Model lifecycle state machine with gates.

tracking -> evaluating -> approved -> canary -> active -> deprecating -> offline
"""

from __future__ import annotations

from datetime import datetime, timedelta

from . import db

STATUSES = ["tracking", "evaluating", "approved", "canary", "active", "deprecating", "offline"]

ALLOWED = {
    "tracking": {"evaluating"},
    "evaluating": {"approved", "rejected"},
    "approved": {"canary"},
    "canary": {"active", "rolled_back"},
    "active": {"deprecating"},
    "deprecating": {"offline"},
    "rejected": set(),
    "rolled_back": {"evaluating"},
    "offline": set(),
}

GATE_COST_TOLERANCE = 1.15
GATE_QUALITY_TOLERANCE = 0.2
GATE_P95_TOLERANCE = 1.2
CANARY_MIN_REQUESTS = 20
CANARY_MAX_ERROR_RATE = 0.01
OFFLINE_MIN_MIGRATION_RATE = 0.99


class LifecycleError(Exception):
    def __init__(self, message: str, details: dict | None = None):
        self.message = message
        self.details = details or {}
        super().__init__(message)


def get_model(model_id: str) -> dict:
    row = db.query_one("SELECT * FROM models WHERE id = ?", (model_id,))
    if not row:
        raise LifecycleError(f"model {model_id} not found")
    return row


def _latest_evaluation(model_id: str) -> dict | None:
    return db.query_one(
        "SELECT * FROM evaluations WHERE model_id = ? ORDER BY run_at DESC LIMIT 1",
        (model_id,),
    )


def _incumbent(model: dict) -> dict | None:
    return db.query_one(
        """
        SELECT * FROM models
        WHERE status = 'active' AND id != ? AND provider_id = ?
        ORDER BY quality_score DESC LIMIT 1
        """,
        (model["id"], model["provider_id"]),
    )


def _check_gate(model: dict, from_status: str, to_status: str) -> dict:
    """Return {'ok': bool, 'checks': [...]} for a transition."""
    checks: list[dict] = []

    if from_status == "evaluating" and to_status == "approved":
        ev = _latest_evaluation(model["id"])
        if not ev:
            return {"ok": False, "checks": [{"name": "evaluation_exists", "ok": False, "detail": "没有评测记录"}]}
        checks.append({"name": "evaluation_exists", "ok": True, "detail": f"{ev['dataset']} @ {ev['run_at']}"})
        inc = _incumbent(model)
        if inc:
            inc_ev = _latest_evaluation(inc["id"])
            inc_quality = float(inc["quality_score"] or 0)
            inc_cost = float(inc_ev["cost_per_1k"]) if inc_ev else None
            inc_p95 = float(inc_ev["p95_latency_ms"]) if inc_ev else None
            checks.append({
                "name": "quality",
                "ok": float(ev["quality_score"]) >= inc_quality - GATE_QUALITY_TOLERANCE,
                "detail": f"{ev['quality_score']:.1f} vs 现役 {inc['id']} {inc_quality:.1f}（允许 -{GATE_QUALITY_TOLERANCE}）",
            })
            if inc_cost is not None:
                checks.append({
                    "name": "cost",
                    "ok": float(ev["cost_per_1k"]) <= inc_cost * GATE_COST_TOLERANCE,
                    "detail": f"{ev['cost_per_1k']:.3f} vs 现役 {inc_cost:.3f}（允许 +{int((GATE_COST_TOLERANCE-1)*100)}%）",
                })
            if inc_p95 is not None:
                checks.append({
                    "name": "p95",
                    "ok": float(ev["p95_latency_ms"]) <= inc_p95 * GATE_P95_TOLERANCE,
                    "detail": f"{ev['p95_latency_ms']:.0f}ms vs 现役 {inc_p95:.0f}ms（允许 +{int((GATE_P95_TOLERANCE-1)*100)}%）",
                })
        return {"ok": all(c["ok"] for c in checks), "checks": checks}

    if from_status == "canary" and to_status == "active":
        since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
        row = db.query_one(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status_code = 200 THEN 1 ELSE 0 END) AS ok
            FROM requests WHERE model_id = ? AND ts >= ?
            """,
            (model["id"], since),
        )
        total = int(row["total"] or 0)
        ok = int(row["ok"] or 0)
        error_rate = 0.0 if total == 0 else 1 - ok / total
        checks.append({
            "name": "canary_traffic",
            "ok": total >= CANARY_MIN_REQUESTS,
            "detail": f"{total} 次请求（至少 {CANARY_MIN_REQUESTS}）",
        })
        checks.append({
            "name": "canary_error_rate",
            "ok": total > 0 and error_rate < CANARY_MAX_ERROR_RATE,
            "detail": f"错误率 {error_rate:.2%}（阈值 {CANARY_MAX_ERROR_RATE:.0%}）",
        })
        p1 = db.query_one(
            "SELECT COUNT(*) AS n FROM incidents WHERE model_id = ? AND severity = 'P1' AND status = 'open'",
            (model["id"],),
        )
        checks.append({
            "name": "no_open_p1",
            "ok": int(p1["n"] or 0) == 0,
            "detail": f"{int(p1['n'] or 0)} 个未关闭 P1",
        })
        return {"ok": all(c["ok"] for c in checks), "checks": checks}

    if from_status == "active" and to_status == "deprecating":
        row = db.query_one("SELECT COUNT(*) AS n FROM migrations WHERE from_model = ?", (model["id"],))
        n = int(row["n"] or 0)
        checks.append({"name": "migration_plan", "ok": n > 0, "detail": f"{n} 个租户在迁移计划中"})
        return {"ok": all(c["ok"] for c in checks), "checks": checks}

    if from_status == "deprecating" and to_status == "offline":
        row = db.query_one(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS done
            FROM migrations WHERE from_model = ?
            """,
            (model["id"],),
        )
        total = int(row["total"] or 0)
        done = int(row["done"] or 0)
        rate = 0.0 if total == 0 else done / total
        checks.append({
            "name": "migration_complete",
            "ok": total > 0 and rate >= OFFLINE_MIN_MIGRATION_RATE,
            "detail": f"{done}/{total} 完成（要求 ≥{OFFLINE_MIN_MIGRATION_RATE:.0%}）",
        })
        return {"ok": all(c["ok"] for c in checks), "checks": checks}

    return {"ok": True, "checks": []}


def transition(model_id: str, to_status: str, reason: str, actor: str = "ops") -> dict:
    model = get_model(model_id)
    from_status = model["status"]
    if to_status not in ALLOWED.get(from_status, set()):
        raise LifecycleError(
            f"不允许从 {from_status} 流转到 {to_status}",
            {"allowed": sorted(ALLOWED.get(from_status, []))},
        )
    gate = _check_gate(model, from_status, to_status)
    if not gate["ok"]:
        raise LifecycleError("流转门槛未通过", {"checks": gate["checks"]})

    db.execute("UPDATE models SET status = ? WHERE id = ?", (to_status, model_id))
    db.execute(
        "INSERT INTO lifecycle_events (model_id, from_status, to_status, reason, actor, ts) VALUES (?,?,?,?,?,?)",
        (model_id, from_status, to_status, reason, actor, datetime.now().strftime("%Y-%m-%dT%H:%M:%S")),
    )
    return {"model_id": model_id, "from": from_status, "to": to_status, "checks": gate["checks"]}


def history(model_id: str) -> list[dict]:
    return db.query(
        "SELECT * FROM lifecycle_events WHERE model_id = ? ORDER BY ts",
        (model_id,),
    )


def board() -> list[dict]:
    rows = db.query(
        "SELECT id, display_name, provider_id, status, canary_percent, quality_score FROM models ORDER BY id"
    )
    grouped = {s: [] for s in STATUSES}
    for r in rows:
        grouped.setdefault(r["status"], []).append(r)
    return [{"status": s, "models": grouped[s]} for s in STATUSES if grouped.get(s)]
