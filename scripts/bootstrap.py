"""One-command demo bootstrap: reset data, replay, evaluate, write a report.

Usage:
    python scripts/bootstrap.py
    python scripts/bootstrap.py --count 500 --days 7
    python scripts/bootstrap.py --keep-data
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import alerts, db, evaluation, reports  # noqa: E402
from scripts import replay  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--keep-data", action="store_true", help="do not reset the SQLite database")
    args = parser.parse_args()

    if args.keep_data:
        db.init_db()
    else:
        db.reset_db()

    rows = replay.build_rows(args.count, args.days)
    replay.insert_rows(rows)
    new_alerts = alerts.scan()
    results = evaluation.run()
    report = evaluation.report(results)
    eval_path = ROOT / "docs" / "evaluation-report.md"
    eval_path.write_text(report, encoding="utf-8")
    daily_path, _ = reports.generate_daily()

    print(f"seeded {args.count} requests over {args.days} days")
    print(f"alerts: {len(new_alerts)} new")
    print(f"evaluation: {eval_path}")
    print(f"daily report: {daily_path}")
    print()
    print("next:")
    print("  python -m uvicorn app.main:app --host 127.0.0.1 --port 8080")
    print("  open http://127.0.0.1:8080/dashboard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
