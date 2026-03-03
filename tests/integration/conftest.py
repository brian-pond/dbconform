"""
Pytest fixtures for integration tests (SQLite, PostgreSQL).

Strategy: tmp_path for SQLite; per-test DB for Postgres when DBCONFORM_TEST_POSTGRES_URL is set.
See docs/technical/01-test-database.md.
"""

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url


def _normalize_postgres_url(url: str) -> str:
    """Ensure URL uses postgresql+psycopg driver for SQLAlchemy."""
    if "+psycopg" not in url.split("?")[0]:
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


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
    db_path = tmp_path / "dbconform_test.db"
    url = f"sqlite:///{db_path!s}"
    engine = create_engine(url)
    # Create the DB file by opening and closing a connection; then release it.
    with engine.connect():
        pass
    engine.dispose()
    yield (db_path, url)
    # tmp_path is cleaned by pytest (last N runs retained for debugging on failure).


@pytest.fixture
def empty_postgres_db() -> tuple[str, str]:
    """
    Provide an empty PostgreSQL database for the test.

    Yields (url, target_schema). Skips if DBCONFORM_TEST_POSTGRES_URL is unset.
    See docs/technical/01-test-database.md.
    """
    env_url = os.environ.get("DBCONFORM_TEST_POSTGRES_URL")
    if not env_url:
        pytest.skip(
            "PostgreSQL not available: set DBCONFORM_TEST_POSTGRES_URL "
            "(e.g. run 'dbconform test postgres up' and use the printed URL)."
        )
    normalized = _normalize_postgres_url(env_url)
    parsed = make_url(normalized)
    # Use URL.create() so the password is preserved (str(URL) can mask it in some versions).
    admin_url = URL.create(
        parsed.drivername,
        parsed.username,
        parsed.password,
        host=parsed.host,
        port=parsed.port,
        database="postgres",
    )

    test_db_name = "dbconform_test_" + uuid.uuid4().hex[:12]
    engine_admin = create_engine(admin_url)
    try:
        with engine_admin.connect() as conn:
            conn = conn.execution_options(isolation_level="AUTOCOMMIT")
            conn.execute(text(f'CREATE DATABASE "{test_db_name}"'))
    finally:
        engine_admin.dispose()

    # Build test DB URL for tests to use. When admin_url is a URL object (env path), build
    # the string manually from components so the password is included; str(admin_url) would
    # mask it and cause the same authentication failure when tests call create_engine(url).
    if isinstance(admin_url, URL):
        test_url_str = (
            f"{admin_url.drivername}://{admin_url.username}:{admin_url.password}"
            f"@{admin_url.host}:{admin_url.port}/{test_db_name}"
        )
    else:
        parsed = make_url(admin_url)
        test_url_str = str(parsed.set(database=test_db_name))

    yield (test_url_str, "public")

    # Teardown: terminate other sessions using the test DB, then drop it.
    engine_teardown = create_engine(admin_url)
    try:
        with engine_teardown.connect() as conn:
            conn = conn.execution_options(isolation_level="AUTOCOMMIT")
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :db AND pid <> pg_backend_pid()"
                ),
                {"db": test_db_name},
            )
            conn.execute(text(f'DROP DATABASE "{test_db_name}"'))
    finally:
        engine_teardown.dispose()


@pytest.fixture(params=["sqlite", "postgres"])
def empty_db(request: pytest.FixtureRequest) -> tuple[str, str | None]:
    """
    Parametrized fixture: same test runs for SQLite and PostgreSQL.

    Yields (url, target_schema): target_schema is None for SQLite, "public" for PostgreSQL.
    PostgreSQL param is skipped when empty_postgres_db is unavailable (see empty_postgres_db).
    """
    if request.param == "sqlite":
        _path, url = request.getfixturevalue("empty_sqlite_db")
        yield (url, None)
    else:
        url, schema = request.getfixturevalue("empty_postgres_db")
        yield (url, schema)
