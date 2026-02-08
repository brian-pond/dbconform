"""
Integration tests: ModelSync.compare() against a real SQLite database.

Traceability: docs/requirements/01-functional.md — Model discovery and API,
Database connection, compare() / do_sync(). Acceptance: schema (create tables, columns).
"""

from pathlib import Path

from sqlalchemy import create_engine, text

import modelsync
from tests.shared_models import SimpleTable


def test_empty_sqlite_db_fixture(empty_sqlite_db: tuple[Path, str]) -> None:
    """Use empty_sqlite_db fixture: DB exists, is writable, and can have tables created."""
    path, url = empty_sqlite_db
    assert isinstance(path, Path)
    assert path.suffix == ".db"
    assert path.exists()

    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY)"))
        conn.commit()
        result = conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))
        names = [row[0] for row in result]
    engine.dispose()
    assert "t" in names


def test_compare_empty_db_returns_create_step(empty_sqlite_db: tuple[Path, str]) -> None:
    """Scenario 1: model has table, DB does not — plan contains CREATE TABLE (01-functional)."""
    _path, url = empty_sqlite_db
    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)
    result = sync.compare(SimpleTable)
    assert not isinstance(result, modelsync.SyncError), str(result)
    plan = result
    assert len(plan.steps) == 1
    assert "simple_table" in plan.sql()
    assert "CREATE TABLE" in plan.sql()


def test_compare_with_connection(empty_sqlite_db: tuple[Path, str]) -> None:
    """Caller passes connection; compare returns plan (01-functional: pass existing connection)."""
    _path, url = empty_sqlite_db
    engine = create_engine(url)
    with engine.connect() as conn:
        sync = modelsync.ModelSync(connection=conn, target_schema=None)
        result = sync.compare(SimpleTable)
    engine.dispose()
    assert not isinstance(result, modelsync.SyncError)
    assert len(result.steps) == 1


def test_compare_after_create_same_schema_no_steps(empty_sqlite_db: tuple[Path, str]) -> None:
    """Scenario 3: table exists in DB and matches model — no steps (schema parity)."""
    _path, url = empty_sqlite_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE simple_table "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(255) NOT NULL, "
                "value FLOAT NOT NULL, count INTEGER NOT NULL)"
            )
        )
        conn.commit()
    with engine.connect() as conn:
        sync = modelsync.ModelSync(connection=conn, target_schema=None)
        result = sync.compare(SimpleTable)
    engine.dispose()
    assert not isinstance(result, modelsync.SyncError)
    assert len(result.steps) == 0


def test_compare_extra_table_in_db_reported_not_dropped(empty_sqlite_db: tuple[Path, str]) -> None:
    """Scenario 2: DB has table not in model — reported in extra_tables, no DROP (01-functional)."""
    _path, url = empty_sqlite_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE other_table (id INTEGER PRIMARY KEY)"))
        conn.commit()
    with engine.connect() as conn:
        sync = modelsync.ModelSync(connection=conn, target_schema=None)
        result = sync.compare(SimpleTable)
    engine.dispose()
    assert not isinstance(result, modelsync.SyncError)
    assert len(result.extra_tables) == 1
    assert result.extra_tables[0].name == "other_table"
    assert not any("DROP" in (s.sql or "") for s in result.steps)


def test_do_sync_applies_plan_then_recompare_parity(empty_sqlite_db: tuple[Path, str]) -> None:
    """Table missing; do_sync applies CREATE; recompare yields 0 steps (01-functional)."""
    _path, url = empty_sqlite_db
    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)
    result = sync.do_sync(SimpleTable)
    assert not isinstance(result, modelsync.SyncError), str(result)
    plan = result
    assert len(plan.steps) == 1
    assert "CREATE TABLE" in plan.sql()
    recompare = sync.compare(SimpleTable)
    assert not isinstance(recompare, modelsync.SyncError)
    assert len(recompare.steps) == 0


def test_compare_invalid_model_returns_sync_error(empty_sqlite_db: tuple[Path, str]) -> None:
    """Passing a class with no __table__ returns SyncError (01-functional: Error handling)."""
    _path, url = empty_sqlite_db
    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)

    class NotATable:
        """Plain class; no __table__, not a mapped model."""

    result = sync.compare(NotATable)
    assert isinstance(result, modelsync.SyncError)
    assert len(result.messages) >= 1
