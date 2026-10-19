"""Test configuration: offline data, temporary SQLite DB, no background scheduler."""
import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="mw-test-"))
os.environ["OFFLINE_MODE"] = "true"
os.environ["DATA_DIR"] = str(_TMP)
os.environ["MARKETWATCH_NO_SCHEDULER"] = "1"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["SMTP_HOST"] = ""
os.environ["NEWS_CACHE_SECONDS"] = "1800"

import pytest  # noqa: E402

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    from app.db import init_db, session_scope

    init_db()
    with session_scope() as s:
        yield s
