"""SQLite access layer and seed data for ModelOps Console."""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")
_lock = threading.Lock()
_initialized = False

NAMED_TENANTS = {
    1: "星河科技",
    2: "云图数据",
    3: "南风传媒",
    4: "极光教育",
    5: "小满电商",
    6: "远山物流",
    7: "蓝鲸医疗",
    8: "一叶出行",
}


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def query(sql: str, params: tuple = ()) -> list[dict]:
    with closing(get_conn()) as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def query_one(sql: str, params: tuple = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple = ()) -> None:
    with closing(get_conn()) as conn:
        conn.execute(sql, params)
        conn.commit()


def executemany(sql: str, rows: list[tuple]) -> None:
    with closing(get_conn()) as conn:
        conn.executemany(sql, rows)
        conn.commit()


def init_db(seed_data: bool = True) -> None:
    global _initialized
    with _lock:
        if _initialized:
            return
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with closing(get_conn()) as conn:
            conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
            cols = {row[1] for row in conn.execute("PRAGMA table_info(models)")}
            if "canary_percent" not in cols:
                conn.execute("ALTER TABLE models ADD COLUMN canary_percent REAL NOT NULL DEFAULT 0")
            if seed_data and conn.execute("SELECT COUNT(*) FROM providers").fetchone()[0] == 0:
                _seed(conn)
            conn.execute(
                "UPDATE models SET canary_percent = 0.10 WHERE id = 'deepseek-chat-v3' AND canary_percent = 0"
            )
            conn.commit()
        _initialized = True


def reset_db() -> None:
    """Drop the database and force re-initialisation (tests only)."""
    global _initialized
    with _lock:
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(config.DB_PATH) + suffix)
            for _ in range(10):
                if not p.exists():
                    break
                try:
                    p.unlink()
                    break
                except PermissionError:
                    time.sleep(0.1)
        _initialized = False
    init_db()


def _seed(conn: sqlite3.Connection) -> None:
    today = date.today()
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    providers = [
        ("prov_openai", "OpenAI (compatible)", "active", "99.9%", "US"),
        ("prov_domestic", "Domestic Cloud", "active", "99.5%", "CN"),
        ("prov_selfhost", "Self-hosted GPU", "active", "99.0%", "CN"),
    ]
    conn.executemany("INSERT INTO providers VALUES (?,?,?,?,?)", providers)

    models = [
        # id, provider, display, version, ctx, modality, status, canary%, quality, release, deprecation, fallback, notes
        ("gpt-4o-mini", "prov_openai", "GPT-4o mini", "2024-07", 128000, "text", "active", 0.0, 8.5,
         "2024-07-18", None, "deepseek-chat", "低成本通用模型"),
        ("gpt-4o", "prov_openai", "GPT-4o", "2024-05", 128000, "text", "active", 0.0, 9.2,
         "2024-05-13", None, "gpt-4o-mini", "高质量旗舰"),
        ("deepseek-chat", "prov_domestic", "DeepSeek Chat", "v2", 64000, "text", "active", 0.0, 8.2,
         "2025-01-20", "2026-12-31", "qwen-plus", "主力国产模型，下月涨价 15%"),
        ("deepseek-chat-v3", "prov_domestic", "DeepSeek Chat", "v3", 128000, "text", "canary", 0.10, 8.6,
         "2026-10-01", None, "deepseek-chat", "候选替代版本，10% 灰度中"),
        ("qwen-plus", "prov_domestic", "Qwen Plus", "2025-04", 128000, "text", "active", 0.0, 8.0,
         "2025-04-01", None, "glm-4", "国产通用，性价比高"),
        ("glm-4", "prov_domestic", "GLM-4", "2025-01", 128000, "text", "active", 0.0, 7.8,
         "2025-01-15", None, "qwen-plus", "中文场景稳定"),
        ("llama-3.1-8b", "prov_selfhost", "Llama 3.1 8B", "2024-07", 32000, "text", "active", 0.0, 7.2,
         "2024-07-23", None, "qwen-plus", "自建推理，成本最低"),
        ("text-embedding-3-small", "prov_openai", "Embedding 3 Small", "2024-01", 8000, "embedding", "active", 0.0, None,
         "2024-01-25", None, None, "向量模型，按输入计费"),
    ]
    conn.executemany("INSERT INTO models VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", models)

    pricing = [
        ("gpt-4o-mini", "2026-01-01", 0.15, 0.60, "USD"),
        ("gpt-4o", "2026-01-01", 2.50, 10.00, "USD"),
        ("deepseek-chat", "2026-01-01", 0.14, 0.28, "USD"),
        ("deepseek-chat", "2026-11-01", 0.16, 0.32, "USD"),
        ("deepseek-chat-v3", "2026-10-01", 0.16, 0.32, "USD"),
        ("qwen-plus", "2026-01-01", 0.11, 0.28, "USD"),
        ("glm-4", "2026-01-01", 0.14, 0.14, "USD"),
        ("llama-3.1-8b", "2026-01-01", 0.05, 0.05, "USD"),
        ("text-embedding-3-small", "2026-01-01", 0.02, 0.00, "USD"),
    ]
    conn.executemany(
        "INSERT INTO model_pricing (model_id, effective_from, input_price_per_1k, output_price_per_1k, currency) VALUES (?,?,?,?,?)",
        pricing,
    )

    tiers = {
        "enterprise": (600, 600000, 2000.0),
        "pro": (120, 120000, 200.0),
        "free": (20, 20000, 20.0),
    }
    tenants = []
    keys = []
    for i in range(1, 201):
        if i <= 30:
            tier = "enterprise"
        elif i <= 180:
            tier = "pro"
        else:
            tier = "free"
        rpm, tpm, budget = tiers[tier]
        tenant_id = f"tenant-{i:03d}"
        name = NAMED_TENANTS.get(i, f"租户 {i:03d}")
        tenants.append((tenant_id, name, tier, rpm, tpm, budget))
        keys.append((f"sk-{tenant_id}-demo", tenant_id, "active", now))
    conn.executemany("INSERT INTO tenants VALUES (?,?,?,?,?,?)", tenants)
    conn.executemany("INSERT INTO api_keys VALUES (?,?,?,?)", keys)

    evaluations = [
        ("deepseek-chat", "eval-v1-20prompts", 8.2, 0.86, 820.0, 0.21, "2026-10-20T10:00:00"),
        ("qwen-plus", "eval-v1-20prompts", 8.0, 0.82, 760.0, 0.19, "2026-10-20T10:20:00"),
        ("deepseek-chat-v3", "eval-v1-20prompts", 8.6, 0.91, 700.0, 0.24, "2026-10-20T10:40:00"),
    ]
    conn.executemany(
        "INSERT INTO evaluations (model_id, dataset, quality_score, pass_rate, p95_latency_ms, cost_per_1k, run_at) VALUES (?,?,?,?,?,?,?)",
        evaluations,
    )

    incidents = [
        ("INC-20261028-001", "2026-10-28T14:05:00", "rate_limit_storm", "P2", "deepseek-chat",
         "prov_domestic", "open", "on-call", "429 率 12.4%，持续 18 分钟",
         None, None, None),
        ("INC-20261027-002", "2026-10-27T09:30:00", "cost_spike", "P3", "gpt-4o",
         "prov_openai", "closed", "ops-lead", "单日成本环比 +38%",
         "某租户长上下文请求占比从 8% 升到 31%", "增加预算告警；对该租户限流", "2026-10-27T16:20:00"),
    ]
    conn.executemany(
        "INSERT INTO incidents (id, ts, type, severity, model_id, provider_id, status, owner, summary, root_cause, action_items, closed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        incidents,
    )

    # 40 个租户参与 deepseek-chat -> v3 迁移，按 5/20/50/100 分批
    batches = [("5%", 2), ("20%", 6), ("50%", 12), ("100%", 20)]
    tenant_no = 1
    migration_rows = []
    for batch, size in batches:
        for _ in range(size):
            tenant_id = f"tenant-{tenant_no:03d}"
            if batch == "5%":
                status = "completed"
            elif batch == "20%" and tenant_no <= 5:
                status = "in_progress"
            else:
                status = "pending"
            started = "2026-10-25T09:00:00" if status != "pending" else None
            completed = "2026-10-25T18:00:00" if status == "completed" else None
            migration_rows.append(("deepseek-chat", "deepseek-chat-v3", batch, tenant_id, status, started, completed))
            tenant_no += 1
    conn.executemany(
        "INSERT INTO migrations (from_model, to_model, batch, tenant_id, status, started_at, completed_at) VALUES (?,?,?,?,?,?,?)",
        migration_rows,
    )

    lifecycle = [
        ("deepseek-chat-v3", None, "tracking", "供应商发布 v3 预告", "ops", "2026-10-01T09:00:00"),
        ("deepseek-chat-v3", "tracking", "evaluating", "加入评测队列", "ops", "2026-10-05T10:00:00"),
        ("deepseek-chat-v3", "evaluating", "approved", "评测通过：质量 +0.4，成本 +14%，P95 -15%", "ops-lead", "2026-10-20T11:00:00"),
        ("deepseek-chat-v3", "approved", "canary", "10% 灰度，观察 7 天", "ops-lead", "2026-10-25T09:00:00"),
    ]
    conn.executemany(
        "INSERT INTO lifecycle_events (model_id, from_status, to_status, reason, actor, ts) VALUES (?,?,?,?,?,?)",
        lifecycle,
    )
