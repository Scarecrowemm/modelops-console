import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DOCS_DIR = BASE_DIR / "docs"
DASHBOARD_DIR = BASE_DIR / "dashboard"
DB_PATH = Path(os.getenv("MODELOPS_DB", str(DATA_DIR / "modelops.db")))

ADMIN_TOKEN = os.getenv("MODELOPS_ADMIN_TOKEN", "admin-demo")
DEFAULT_MAX_TOKENS = 256
CURRENCY = "USD"

# 运营阈值：告警与日报共用
THRESHOLDS = {
    "success_rate_min": 0.98,
    "p95_latency_ms_max": 2000,
    "rate_limited_ratio_max": 0.05,
    "cost_wow_max": 0.20,
}
