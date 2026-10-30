"""Tenant migration plan and progress tracking."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime

from . import db

CUMULATIVE_BATCHES = (5, 20, 50, 100)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def plan(
    from_model: str,
    to_model: str,
    tenant_ids: list[str] | None = None,
    batches: tuple[int, ...] = CUMULATIVE_BATCHES,
) -> dict:
    if tenant_ids is None:
        tenant_ids = [
            r["tenant_id"]
            for r in db.query("SELECT tenant_id FROM tenants ORDER BY id LIMIT 40")
        ]
    tenant_ids = list(dict.fromkeys(tenant_ids))
    if not tenant_ids:
        raise ValueError("no tenants to migrate")

    db.execute(
        "DELETE FROM migrations WHERE from_model = ? AND to_model = ?",
        (from_model, to_model),
    )

    total = len(tenant_ids)
    rows = []
    start = 0
    prev = 0
    for pct in batches:
        end = total if pct >= 100 else max(start + 1, round(total * pct / 100))
        end = min(end, total)
        chunk = tenant_ids[start:end]
        start = end
        label = f"{pct}%"
        for tenant_id in chunk:
            rows.append((from_model, to_model, label, tenant_id, "pending", None, None))
        if start >= total:
            break
    if start < total:
        for tenant_id in tenant_ids[start:]:
            rows.append((from_model, to_model, f"{batches[-1]}%", tenant_id, "pending", None, None))

    db.executemany(
        "INSERT INTO migrations (from_model, to_model, batch, tenant_id, status, started_at, completed_at) VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    return progress(from_model, to_model)


def progress(from_model: str | None = None, to_model: str | None = None) -> dict:
    where, params = "", []
    if from_model:
        where += " AND from_model = ?"
        params.append(from_model)
    if to_model:
        where += " AND to_model = ?"
        params.append(to_model)
    rows = db.query(
        f"SELECT batch, status, COUNT(*) AS n FROM migrations WHERE 1=1 {where} GROUP BY batch, status",
        tuple(params),
    )
    by_batch: dict[str, dict] = {}
    for r in rows:
        b = by_batch.setdefault(
            r["batch"],
            {"batch": r["batch"], "total": 0, "pending": 0, "in_progress": 0,
             "completed": 0, "rolled_back": 0},
        )
        b["total"] += int(r["n"])
        b[r["status"]] = b.get(r["status"], 0) + int(r["n"])
    ordered = sorted(by_batch.values(), key=lambda x: int(x["batch"].rstrip("%")))
    total = sum(b["total"] for b in ordered)
    completed = sum(b["completed"] for b in ordered)
    for b in ordered:
        b["rate"] = round(b["completed"] / b["total"], 3) if b["total"] else 0.0
    return {
        "total": total,
        "completed": completed,
        "completion_rate": round(completed / total, 3) if total else 0.0,
        "by_batch": ordered,
    }


def complete_batch(batch: str, from_model: str | None = None, to_model: str | None = None) -> int:
    sql = "UPDATE migrations SET status = 'completed', started_at = COALESCE(started_at, ?), completed_at = ? WHERE batch = ? AND status IN ('pending','in_progress')"
    params: list = [_now(), _now(), batch]
    if from_model:
        sql += " AND from_model = ?"
        params.append(from_model)
    if to_model:
        sql += " AND to_model = ?"
        params.append(to_model)
    with closing(db.get_conn()) as conn:
        cur = conn.execute(sql, tuple(params))
        conn.commit()
        return cur.rowcount


def rollback_batch(batch: str, reason: str = "rollback") -> int:
    with closing(db.get_conn()) as conn:
        cur = conn.execute(
            "UPDATE migrations SET status = 'rolled_back' WHERE batch = ? AND status IN ('pending','in_progress')",
            (batch,),
        )
        conn.commit()
        return cur.rowcount


def tenant_status(tenant_id: str) -> list[dict]:
    return db.query(
        "SELECT * FROM migrations WHERE tenant_id = ? ORDER BY id",
        (tenant_id,),
    )
