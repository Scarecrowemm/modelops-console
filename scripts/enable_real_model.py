"""Enable the optional real OpenAI-compatible model.

Requires:
    MODELOPS_REAL_BASE_URL   e.g. http://127.0.0.1:11434/v1
    MODELOPS_REAL_API_KEY    e.g. ollama
    MODELOPS_REAL_MODEL      e.g. qwen2.5:7b

Usage:
    python scripts/enable_real_model.py
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import db, real_provider  # noqa: E402


def main() -> int:
    db.init_db()
    if not real_provider.available():
        print("Set MODELOPS_REAL_BASE_URL, MODELOPS_REAL_API_KEY and MODELOPS_REAL_MODEL first.")
        print("See docs/real-provider.md.")
        return 1

    base = os.getenv("MODELOPS_REAL_BASE_URL", "").rstrip("/")
    model_name = os.getenv("MODELOPS_REAL_MODEL", "")
    today = date.today().isoformat()

    db.execute(
        "INSERT OR IGNORE INTO providers VALUES (?,?,?,?,?)",
        ("prov_real", "OpenAI-compatible (real)", "active", "external", "env"),
    )
    db.execute(
        """
        INSERT OR IGNORE INTO models (
            id, provider_id, display_name, version, context_window, modality,
            status, canary_percent, quality_score, release_date, deprecation_date,
            fallback_model, notes
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "real-chat", "prov_real", "Real Chat (env)", model_name, 128000, "text",
            "active", 0.0, 8.0, today, None, "deepseek-chat", "real OpenAI-compatible upstream",
        ),
    )
    if not db.query_one("SELECT 1 AS x FROM model_pricing WHERE model_id = 'real-chat'"):
        db.execute(
            """
            INSERT INTO model_pricing (model_id, effective_from, input_price_per_1k, output_price_per_1k, currency)
            VALUES (?,?,?,?,?)
            """,
            ("real-chat", today, 0.50, 1.50, "USD"),
        )
    db.execute("UPDATE models SET status = 'active', version = ? WHERE id = 'real-chat'", (model_name,))

    print(f"enabled real-chat -> {model_name} at {base}")
    print("request it with:")
    print('  curl -X POST http://127.0.0.1:8080/v1/chat/completions \\')
    print('    -H "Authorization: Bearer sk-tenant-001-demo" \\')
    print('    -H "Content-Type: application/json" \\')
    print('    -d \'{"model":"real-chat","messages":[{"role":"user","content":"你好"}]}\'')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
