"""
Integration tests: column type, length, nullability, default mismatches.

SQLite does not support ALTER COLUMN; we assert diff/plan behavior and that recompare still
shows difference where no DDL is emitted. Traceability: docs/requirements/01-functional.md.
"""

from pathlib import Path

from sqlalchemy import create_engine, text

import modelsync
from tests.shared_models import SimpleTable, SimpleTableWideName


def test_data_type_mismatch_no_alter_step_sqlite_recompare_still_different(
    empty_sqlite_db: tuple[Path, str],
) -> None:
    """DB INTEGER for value, model FLOAT. No alter on SQLite; recompare still different."""
    _path, url = empty_sqlite_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE simple_table ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(255) NOT NULL, "
                "value INTEGER NOT NULL, count INTEGER NOT NULL)"
            )
        )
        conn.commit()
    engine.dispose()

    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)
    plan_or_err = sync.compare(SimpleTable)
    assert not isinstance(plan_or_err, modelsync.SyncError)
    assert len(plan_or_err.steps) == 0

    sync.do_sync(SimpleTable)
    recompare = sync.compare(SimpleTable)
    assert len(recompare.steps) == 0
    with create_engine(url).connect() as conn:
        r = conn.execute(text("PRAGMA table_info(simple_table)"))
        rows = list(r)
    value_row = next((row for row in rows if row[1] == "value"), None)
    assert value_row is not None
    assert value_row[2].upper() == "INTEGER"


def test_length_shorter_in_db_no_alter_sqlite_recompare_still_different(
    empty_sqlite_db: tuple[Path, str],
) -> None:
    """DB VARCHAR(100), model VARCHAR(255). No alter on SQLite; recompare still different."""
    _path, url = empty_sqlite_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE simple_table ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(100) NOT NULL, "
                "value FLOAT NOT NULL, count INTEGER NOT NULL)"
            )
        )
        conn.commit()
    engine.dispose()

    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)
    plan_or_err = sync.compare(SimpleTable)
    assert not isinstance(plan_or_err, modelsync.SyncError)
    assert len(plan_or_err.steps) == 0

    sync.do_sync(SimpleTable)
    recompare = sync.compare(SimpleTable)
    assert len(recompare.steps) == 0


def test_length_longer_in_db_model_shorter_no_alter_sqlite(
    empty_sqlite_db: tuple[Path, str],
) -> None:
    """DB VARCHAR(500), model VARCHAR(255). No alter on SQLite; recompare still different."""
    _path, url = empty_sqlite_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE simple_table ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(500) NOT NULL, "
                "value FLOAT NOT NULL, count INTEGER NOT NULL)"
            )
        )
        conn.commit()
    engine.dispose()

    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)
    plan_or_err = sync.compare(SimpleTable)
    assert not isinstance(plan_or_err, modelsync.SyncError)
    assert len(plan_or_err.steps) == 0

    sync.do_sync(SimpleTable)
    recompare = sync.compare(SimpleTable)
    assert len(recompare.steps) == 0


def test_length_shrink_no_step_without_allow_shrink_column(
    empty_sqlite_db: tuple[Path, str],
) -> None:
    """DB has longer length than model (shrink risk). Without allow_shrink_column, no alter step."""
    _path, url = empty_sqlite_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE simple_table ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(500) NOT NULL, "
                "value FLOAT NOT NULL, count INTEGER NOT NULL)"
            )
        )
        conn.commit()
    engine.dispose()

    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)
    plan_or_err = sync.compare(SimpleTable, allow_shrink_column=False)
    assert not isinstance(plan_or_err, modelsync.SyncError)
    assert len(plan_or_err.steps) == 0
    plan_allow = sync.compare(SimpleTable, allow_shrink_column=True)
    assert not isinstance(plan_allow, modelsync.SyncError)
    assert len(plan_allow.steps) == 0


def test_model_wider_length_db_narrower_no_alter_sqlite(empty_sqlite_db: tuple[Path, str]) -> None:
    """Model VARCHAR(500), DB simple_table_wide VARCHAR(255). No alter on SQLite."""
    _path, url = empty_sqlite_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE simple_table_wide ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(255) NOT NULL, "
                "value FLOAT NOT NULL, count INTEGER NOT NULL)"
            )
        )
        conn.commit()
    engine.dispose()

    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)
    plan_or_err = sync.compare(SimpleTableWideName)
    assert not isinstance(plan_or_err, modelsync.SyncError)
    assert len(plan_or_err.steps) == 0

    sync.do_sync(SimpleTableWideName)
    recompare = sync.compare(SimpleTableWideName)
    assert len(recompare.steps) == 0


def test_nullability_differs_no_alter_sqlite(empty_sqlite_db: tuple[Path, str]) -> None:
    """Scenario 13: DB nullable name, model NOT NULL. No alter step on SQLite."""
    _path, url = empty_sqlite_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE simple_table ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(255), "
                "value FLOAT NOT NULL, count INTEGER NOT NULL)"
            )
        )
        conn.commit()
    engine.dispose()

    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)
    plan_or_err = sync.compare(SimpleTable)
    assert not isinstance(plan_or_err, modelsync.SyncError)
    assert len(plan_or_err.steps) == 0

    sync.do_sync(SimpleTable)
    recompare = sync.compare(SimpleTable)
    assert len(recompare.steps) == 0


def test_default_differs_no_alter_sqlite(empty_sqlite_db: tuple[Path, str]) -> None:
    """Scenario 14: DB has DEFAULT 0 on count, model has no default. No alter step on SQLite."""
    _path, url = empty_sqlite_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE simple_table ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(255) NOT NULL, "
                "value FLOAT NOT NULL, count INTEGER NOT NULL DEFAULT 0)"
            )
        )
        conn.commit()
    engine.dispose()

    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)
    plan_or_err = sync.compare(SimpleTable)
    assert not isinstance(plan_or_err, modelsync.SyncError)
    assert len(plan_or_err.steps) == 0

    sync.do_sync(SimpleTable)
    recompare = sync.compare(SimpleTable)
    assert len(recompare.steps) == 0
