"""Replay 1,000 synthetic requests and reconcile the billed cost.

Usage:
    python scripts/replay.py --count 1000 --days 7
    python scripts/replay.py --count 50 --via-http --base-url http://127.0.0.1:8080
"""

from __future__ import annotations

import argparse
import random
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import db, pricing  # noqa: E402

MODEL_WEIGHTS = {
    "deepseek-chat": 0.30,
    "qwen-plus": 0.22,
    "gpt-4o-mini": 0.15,
    "glm-4": 0.10,
    "llama-3.1-8b": 0.08,
    "gpt-4o": 0.05,
    "deepseek-chat-v3": 0.10,
}
TIER_WEIGHTS = {"enterprise": 0.25, "pro": 0.65, "free": 0.10}


def _pick_tenant(tenants: list[dict]) -> dict:
    by_tier = {t: [x for x in tenants if x["tier"] == t] for t in TIER_WEIGHTS}
    tier = random.choices(list(TIER_WEIGHTS), weights=list(TIER_WEIGHTS.values()))[0]
    return random.choice(by_tier[tier])


def _pick_model() -> str:
    return random.choices(list(MODEL_WEIGHTS), weights=list(MODEL_WEIGHTS.values()))[0]


def _ts(days: int) -> str:
    now = datetime.now()
    weights = [0.35] + [0.65 / max(1, days - 1)] * max(0, days - 1)
    weights = weights[:days]
    days_ago = random.choices(range(days), weights=weights)[0]
    day = now - timedelta(days=days_ago)
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now if days_ago == 0 else start + timedelta(days=1) - timedelta(seconds=1)
    span = max(1, int((end - start).total_seconds()))
    return (start + timedelta(seconds=random.randint(0, span))).strftime("%Y-%m-%dT%H:%M:%S")


def _tokens(model_id: str) -> tuple[int, int]:
    prompt = int(random.lognormvariate(5.2, 0.7))
    prompt = max(20, min(prompt, 2000))
    if model_id == "gpt-4o" and random.random() < 0.06:
        prompt = random.randint(3000, 6000)  # long-context abuse drives cost anomalies
    completion = max(10, min(int(random.lognormvariate(4.7, 0.6)), 600))
    return prompt, completion


def _status(model_id: str) -> int:
    if model_id == "deepseek-chat-v3":
        return random.choices([200, 429, 500], weights=[0.992, 0.005, 0.003])[0]
    return random.choices([200, 429, 500, 504], weights=[0.94, 0.035, 0.015, 0.010])[0]


def _latency(model_id: str, status: int) -> int:
    base = {
        "gpt-4o": 900, "gpt-4o-mini": 420, "deepseek-chat": 520,
        "deepseek-chat-v3": 480, "qwen-plus": 460, "glm-4": 500, "llama-3.1-8b": 300,
    }.get(model_id, 500)
    if status != 200:
        return 0
    return max(30, int(base * random.uniform(0.8, 1.35)))


def build_rows(count: int, days: int) -> list[tuple]:
    tenants = db.query("SELECT id, tier FROM tenants")
    models = db.query("SELECT id, fallback_model, provider_id FROM models WHERE modality = 'text'")
    fallback = {m["id"]: m["fallback_model"] for m in models}
    provider = {m["id"]: m["provider_id"] for m in models}
    price_cache: dict[tuple[str, str], dict] = {}

    rows = []
    for _ in range(count):
        tenant = _pick_tenant(tenants)
        requested = _pick_model()
        status = _status(requested)
        route_reason = "direct"
        fallback_from = None
        model_id = requested

        if requested == "deepseek-chat-v3":
            requested = "deepseek-chat"
            route_reason = "migration"
            fallback_from = "deepseek-chat"
        elif status != 200 and fallback.get(requested) and random.random() < 0.6:
            model_id = fallback[requested]
            route_reason = "fallback"
            fallback_from = requested
            status = 200  # fallback succeeded

        ts = _ts(days)
        prompt_tokens, completion_tokens = _tokens(model_id)
        if status != 200:
            prompt_tokens, completion_tokens = 0, 0
            cost = 0.0
        else:
            key = (model_id, ts[:10])
            if key not in price_cache:
                price_cache[key] = pricing.get_price(model_id, datetime.fromisoformat(ts))
            p = price_cache[key]
            cost = round(
                prompt_tokens / 1000 * float(p["input_price_per_1k"])
                + completion_tokens / 1000 * float(p["output_price_per_1k"]),
                6,
            )

        rows.append(
            (
                "chatcmpl-" + uuid.uuid4().hex[:24], ts, tenant["id"],
                f"sk-{tenant['id']}-demo", requested, model_id,
                provider[model_id],
                prompt_tokens, completion_tokens, cost, _latency(model_id, status),
                status, None if status == 200 else ("rate_limited" if status == 429 else "upstream_error"),
                route_reason, fallback_from, 0,
            )
        )
    return rows


INSERT_SQL = """
INSERT INTO requests (
    request_id, ts, tenant_id, key_id, requested_model, model_id, provider_id,
    prompt_tokens, completion_tokens, cost, latency_ms, status_code, error_type,
    route_reason, fallback_from, cached
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


def insert_rows(rows: list[tuple]) -> None:
    for i in range(0, len(rows), 500):
        db.executemany(INSERT_SQL, rows[i:i + 500])


def reconcile() -> dict:
    rows = db.query(
        "SELECT request_id, ts, model_id, prompt_tokens, completion_tokens, cost FROM requests WHERE status_code = 200"
    )
    cache: dict[tuple[str, str], dict] = {}
    total_stored = 0.0
    total_recalc = 0.0
    max_diff = 0.0
    bad = 0
    for r in rows:
        key = (r["model_id"], r["ts"][:10])
        if key not in cache:
            cache[key] = pricing.get_price(r["model_id"], datetime.fromisoformat(r["ts"]))
        p = cache[key]
        recalc = (
            r["prompt_tokens"] / 1000 * float(p["input_price_per_1k"])
            + r["completion_tokens"] / 1000 * float(p["output_price_per_1k"])
        )
        diff = abs(recalc - float(r["cost"]))
        max_diff = max(max_diff, diff)
        total_stored += float(r["cost"])
        total_recalc += recalc
        if diff > 0.01:
            bad += 1
    total_diff_pct = abs(total_recalc - total_stored) / total_stored * 100 if total_stored else 0.0
    return {
        "rows": len(rows),
        "total_stored": round(total_stored, 4),
        "total_recalc": round(total_recalc, 4),
        "max_diff": round(max_diff, 8),
        "total_diff_pct": round(total_diff_pct, 6),
        "rows_over_1_cent": bad,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--via-http", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()

    random.seed(args.seed)
    db.init_db()

    if args.via_http:
        import httpx

        ok = 0
        for i in range(args.count):
            tenant = _pick_tenant(db.query("SELECT id, tier FROM tenants"))
            model = _pick_model()
            if model == "deepseek-chat-v3":
                model = "deepseek-chat"
            r = httpx.post(
                f"{args.base_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer sk-{tenant['id']}-demo"},
                json={"model": model, "messages": [{"role": "user", "content": f"回放请求 {i}"}]},
                timeout=30,
            )
            ok += 1 if r.status_code == 200 else 0
        print(f"via-http: {ok}/{args.count} succeeded")
        return 0

    rows = build_rows(args.count, args.days)
    insert_rows(rows)

    summary = db.query_one(
        """
        SELECT COUNT(*) AS n, ROUND(SUM(cost), 4) AS cost,
               ROUND(AVG(CASE WHEN status_code = 200 THEN 1.0 ELSE 0 END), 4) AS success,
               ROUND(AVG(CASE WHEN status_code = 429 THEN 1.0 ELSE 0 END), 4) AS limited
        FROM requests
        """
    )
    print(f"inserted: {summary['n']} requests, cost ${summary['cost']}, "
          f"success {summary['success']:.2%}, 429 {summary['limited']:.2%}")
    by_model = db.query(
        "SELECT model_id, COUNT(*) n, ROUND(SUM(cost),4) cost FROM requests GROUP BY model_id ORDER BY cost DESC"
    )
    for r in by_model:
        print(f"  {r['model_id']:<22} {r['n']:>5} req  ${r['cost']}")

    rec = reconcile()
    print(f"reconcile: rows={rec['rows']} stored=${rec['total_stored']} recalc=${rec['total_recalc']} "
          f"max_diff={rec['max_diff']} total_diff={rec['total_diff_pct']}% rows>1c={rec['rows_over_1_cent']}")
    if rec["total_diff_pct"] >= 1.0 or rec["rows_over_1_cent"] > 0:
        print("RECONCILIATION FAILED")
        return 1
    print("RECONCILIATION OK (<1%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
