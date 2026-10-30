"""Run the 20-prompt evaluation across active models and write the report.

Usage:
    python scripts/eval_demo.py
    python scripts/eval_demo.py deepseek-chat qwen-plus deepseek-chat-v3
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import db, evaluation  # noqa: E402


def main() -> int:
    db.init_db()
    model_ids = sys.argv[1:] or None
    results = evaluation.run(model_ids)
    report = evaluation.report(results)
    path = ROOT / "docs" / "evaluation-report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
    print(report)
    print(f"written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
