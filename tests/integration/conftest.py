"""
Pytest fixtures for integration tests.

Test database strategy (docs/technical/01-test-database.md):
- Use pytest's tmp_path (not home dir) for writable, isolated, auto-cleaned paths.
- Each test gets a fresh empty SQLite DB via empty_sqlite_db fixture.
- Teardown: engine disposed in fixture; tmp_path is removed by pytest after the run.
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine


@pytest.fixture
def empty_sqlite_db(tmp_path: Path) -> tuple[Path, str]:
    """
    Provide a new, empty SQLite database for the test.

    The file is created under pytest's temporary directory (tmp_path), so there
    are no permission issues and pytest cleans it up after the run (with
    retention for the last few runs on failure). Each test gets its own DB file
    for isolation.

    Yields:
        (path, url): pathlib.Path to the .db file and SQLAlchemy URL string.
    """
    db_path = tmp_path / "modelsync_test.db"
    url = f"sqlite:///{db_path!s}"
    engine = create_engine(url)
    # Create the DB file by opening and closing a connection; then release it.
    with engine.connect():
        pass
    engine.dispose()
    yield (db_path, url)
    # tmp_path is cleaned by pytest (last N runs retained for debugging on failure).
