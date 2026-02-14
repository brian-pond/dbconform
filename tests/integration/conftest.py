"""
Pytest fixtures for integration tests.

Test database strategy (docs/technical/01-test-database.md):
- Use pytest's tmp_path (not home dir) for writable, isolated, auto-cleaned paths.
- Each test gets a fresh empty SQLite DB via empty_sqlite_db fixture.
- PostgreSQL: empty_postgres_db uses MODELSYNC_TEST_POSTGRES_URL or pytest-docker;
  per-test DB for isolation. Skip if neither available.
- Teardown: engine disposed in fixture; tmp_path is removed by pytest after the run.
"""

import os
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url, URL


def _wait_for_postgres(url: str, timeout_seconds: float = 15.0) -> None:
    """Retry connecting to Postgres until ready (e.g. when compose was started without --wait)."""
    engine = create_engine(url)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with engine.connect():
                pass
        except Exception:
            time.sleep(0.5)
        else:
            engine.dispose()
            return
    engine.dispose()
    raise RuntimeError(f"Postgres at {url!r} did not become ready within {timeout_seconds}s")


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
    db_path = tmp_path / "modelsync_test.db"
    url = f"sqlite:///{db_path!s}"
    engine = create_engine(url)
    # Create the DB file by opening and closing a connection; then release it.
    with engine.connect():
        pass
    engine.dispose()
    yield (db_path, url)
    # tmp_path is cleaned by pytest (last N runs retained for debugging on failure).


@pytest.fixture
def empty_postgres_db(request: pytest.FixtureRequest) -> tuple[str, str]:
    """
    Provide an empty PostgreSQL database for the test.

    Uses MODELSYNC_TEST_POSTGRES_URL if set (admin operations use same host with
    database=postgres). Otherwise uses pytest-docker (docker-compose postgres
    service). Creates a unique database per test for isolation; drops it on teardown.

    Yields:
        (url, target_schema): SQLAlchemy URL (postgresql+psycopg://...) and schema name "public".

    Skips if neither env URL nor Docker Postgres is available (requires [postgres] extra).
    """
    env_url = os.environ.get("MODELSYNC_TEST_POSTGRES_URL")
    if env_url:
        normalized = _normalize_postgres_url(env_url)
        parsed = make_url(normalized)
        # Use URL.create() instead of str(parsed.set(...)): in some SQLAlchemy versions,
        # str(URL) masks the password (e.g. postgresql://user:***@host/db), and create_engine()
        # then receives that literal "***" and connection fails with "password authentication
        # failed". Building from components preserves the real password.
        admin_url = URL.create(
            parsed.drivername,
            parsed.username,
            parsed.password,
            host=parsed.host,
            port=parsed.port,
            database="postgres",
        )
    else:
        try:
            docker_services = request.getfixturevalue("docker_services")
            docker_ip = request.getfixturevalue("docker_ip")
        except Exception as e:
            pytest.skip(
                f"PostgreSQL not available: set MODELSYNC_TEST_POSTGRES_URL or use pytest-docker. Reason: {e!s}"
            )
        port = docker_services.port_for("postgres", 5432)
        admin_url = f"postgresql+psycopg://postgres:postgres@{docker_ip}:{port}/postgres"
        _wait_for_postgres(admin_url)

    test_db_name = "modelsync_test_" + uuid.uuid4().hex[:12]
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

    engine_teardown = create_engine(admin_url)
    try:
        with engine_teardown.connect() as conn:
            conn = conn.execution_options(isolation_level="AUTOCOMMIT")
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
