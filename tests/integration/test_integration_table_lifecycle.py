"""
Integration tests: table-level lifecycle (missing, identical, extra, two tables).

Traceability: docs/requirements/01-functional.md — Schema parity, add/alter only.
Pattern: create table(s), compare, assert plan, do_sync or no-op, recompare, assert.
"""

from pathlib import Path

from sqlalchemy import create_engine, text

import modelsync
from tests.shared_models import OtherTable, SimpleTable


def test_table_missing_do_sync_then_parity(empty_sqlite_db: tuple[Path, str]) -> None:
    """Table does not exist. Plan CREATE TABLE; do_sync applies; recompare 0 steps."""
    _path, url = empty_sqlite_db
    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)
    plan_or_err = sync.compare(SimpleTable)
    assert not isinstance(plan_or_err, modelsync.SyncError), str(plan_or_err)
    assert len(plan_or_err.steps) == 1
    assert "simple_table" in plan_or_err.sql() and "CREATE TABLE" in plan_or_err.sql()

    result = sync.do_sync(SimpleTable)
    assert not isinstance(result, modelsync.SyncError), str(result)
    assert len(result.steps) == 1

    recompare = sync.compare(SimpleTable)
    assert not isinstance(recompare, modelsync.SyncError)
    assert len(recompare.steps) == 0


def test_table_exists_identical_schema_no_steps(empty_sqlite_db: tuple[Path, str]) -> None:
    """Scenario 2: Table exists, identical schema. 0 steps; do_sync no-op; recompare 0 steps."""
    _path, url = empty_sqlite_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE simple_table ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(255) NOT NULL, "
                "value FLOAT NOT NULL, count INTEGER NOT NULL)"
            )
        )
        conn.commit()
    engine.dispose()

    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)
    plan_or_err = sync.compare(SimpleTable)
    assert not isinstance(plan_or_err, modelsync.SyncError)
    assert len(plan_or_err.steps) == 0

    result = sync.do_sync(SimpleTable)
    assert not isinstance(result, modelsync.SyncError)
    recompare = sync.compare(SimpleTable)
    assert len(recompare.steps) == 0


def test_extra_table_reported_no_drop_recompare_still_extra(
    empty_sqlite_db: tuple[Path, str],
) -> None:
    """Extra table in DB. extra_tables reported; no DROP; recompare still has extra."""
    _path, url = empty_sqlite_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE other_table (id INTEGER PRIMARY KEY)"))
        conn.commit()
    engine.dispose()

    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)
    plan_or_err = sync.compare(SimpleTable)
    assert not isinstance(plan_or_err, modelsync.SyncError)
    assert len(plan_or_err.extra_tables) == 1
    assert plan_or_err.extra_tables[0].name == "other_table"
    assert not any("DROP" in (s.sql or "") for s in plan_or_err.steps)

    sync.do_sync(SimpleTable)
    recompare = sync.compare(SimpleTable)
    assert len(recompare.extra_tables) == 1
    assert recompare.extra_tables[0].name == "other_table"


def test_two_tables_one_missing_do_sync_both_present(
    empty_sqlite_db: tuple[Path, str],
) -> None:
    """Two tables in model; one missing. Plan CREATE missing; do_sync; recompare 0 steps."""
    _path, url = empty_sqlite_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE simple_table ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(255) NOT NULL, "
                "value FLOAT NOT NULL, count INTEGER NOT NULL)"
            )
        )
        conn.commit()
    engine.dispose()

    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)
    plan_or_err = sync.compare([SimpleTable, OtherTable])
    assert not isinstance(plan_or_err, modelsync.SyncError)
    assert len(plan_or_err.steps) == 1
    assert "other_table" in plan_or_err.sql()

    result = sync.do_sync([SimpleTable, OtherTable])
    assert not isinstance(result, modelsync.SyncError)
    recompare = sync.compare([SimpleTable, OtherTable])
    assert len(recompare.steps) == 0
