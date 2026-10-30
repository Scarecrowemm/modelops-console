import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_tmp = Path(tempfile.mkdtemp(prefix="modelops-test-"))
os.environ["MODELOPS_DB"] = str(_tmp / "test.db")
os.environ["MODELOPS_ADMIN_TOKEN"] = "test-admin"

import pytest  # noqa: E402

from app import db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_db():
    db.init_db()
    yield


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


@pytest.fixture()
def fresh_db():
    db.reset_db()
    yield
