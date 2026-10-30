"""Daily operations job: append synthetic traffic, scan alerts, check canary,
write the daily report, and (on Mondays) run the weekly review.

Usage:
    python scripts/daily_job.py
    python scripts/daily_job.py --count 200 --no-replay
    python scripts/daily_job.py --eval          # force evaluation today
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import alerts, db, evaluation, reports  # noqa: E402
from scripts import canary_check, replay  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=200, help="requests to append for today")
    parser.add_argument("--no-replay", action="store_true")
    parser.add_argument("--eval", action="store_true", help="force evaluation even if not Monday")
    args = parser.parse_args()

    db.init_db()

    if not args.no_replay:
        replay.insert_rows(replay.build_rows(args.count, 1))

    new_alerts = alerts.scan()
    canary_actions = canary_check.check()
    daily_path, _ = reports.generate_daily()

    print(f"date: {date.today().isoformat()}")
    print(f"new alerts: {len(new_alerts)}")
    for a in new_alerts:
        print(f"  [{a['severity']}] {a['rule']}: {a['message']}")
    for c in canary_actions:
        print(f"canary {c['model_id']}: {c['action']} ({c['reason']})")
    print(f"daily report: {daily_path}")

    if args.eval or date.today().weekday() == 0:
        results = evaluation.run()
        (ROOT / "docs" / "evaluation-report.md").write_text(
            evaluation.report(results), encoding="utf-8"
        )
        weekly_path, _ = reports.generate_weekly()
        print(f"weekly report: {weekly_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
