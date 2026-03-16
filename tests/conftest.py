"""Shared pytest fixtures for all test suites."""
import json
import sys
from pathlib import Path

# Make the backend package importable
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pytest

CACHE_PATH = ROOT / 'data' / 'email_cache.json'


@pytest.fixture(scope='session')
def email_cache():
    """Load the email cache JSON for parsing tests."""
    if not CACHE_PATH.exists():
        return []
    with open(CACHE_PATH, encoding='utf-8') as f:
        return json.load(f)


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Initialise a temporary SQLite DB with the full schema and patch DB_PATH."""
    db_path = str(tmp_path / 'test.db')

    import backend.database as db_module
    monkeypatch.setattr(db_module.settings, 'DB_PATH', db_path)

    from backend.database import init_database
    init_database()

    yield db_path
