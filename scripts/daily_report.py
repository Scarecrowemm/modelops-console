"""Generate a daily operations report.

Usage:
    python scripts/daily_report.py            # today
    python scripts/daily_report.py 2026-10-28
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import db, reports  # noqa: E402


def main() -> int:
    db.init_db()
    day = sys.argv[1] if len(sys.argv) > 1 else None
    path, content = reports.generate_daily(day)
    print(path)
    print()
    print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
