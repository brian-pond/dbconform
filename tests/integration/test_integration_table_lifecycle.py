"""
Integration tests: table-level lifecycle (missing, identical, extra, two tables).

Traceability: docs/requirements/01-functional.md — Schema parity, add/alter only.
Pattern: create table(s), compare, assert plan, do_sync or no-op, recompare, assert.
"""

from sqlalchemy import create_engine, text

import modelsync
from tests.shared_models import OtherTable, SimpleTable


def test_table_missing_do_sync_then_parity(empty_db: tuple[str, str | None]) -> None:
    """Table does not exist. Plan CREATE TABLE; do_sync applies; recompare 0 steps."""
    url, target_schema = empty_db
    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=target_schema)
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


def test_table_exists_identical_schema_no_steps(empty_db: tuple[str, str | None]) -> None:
    """Scenario 2: Table exists, identical schema. 0 steps; do_sync no-op; recompare 0 steps."""
    url, target_schema = empty_db
    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=target_schema)
    sync.do_sync(SimpleTable)
    plan_or_err = sync.compare(SimpleTable)
    assert not isinstance(plan_or_err, modelsync.SyncError)
    assert len(plan_or_err.steps) == 0

    result = sync.do_sync(SimpleTable)
    assert not isinstance(result, modelsync.SyncError)
    recompare = sync.compare(SimpleTable)
    assert len(recompare.steps) == 0


def test_extra_table_reported_no_drop_recompare_still_extra(
    empty_db: tuple[str, str | None],
) -> None:
    """Extra table in DB. extra_tables reported; no DROP; recompare still has extra."""
    url, target_schema = empty_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE other_table (id INTEGER PRIMARY KEY)"))
        conn.commit()
    engine.dispose()

    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=target_schema)
    plan_or_err = sync.compare(SimpleTable)
    assert not isinstance(plan_or_err, modelsync.SyncError)
    assert len(plan_or_err.extra_tables) == 1
    assert plan_or_err.extra_tables[0].name == "other_table"
    assert not any("DROP" in (s.sql or "") for s in plan_or_err.steps)

    sync.do_sync(SimpleTable)
    recompare = sync.compare(SimpleTable)
    assert len(recompare.extra_tables) == 1
    assert recompare.extra_tables[0].name == "other_table"


def test_extra_table_dropped_when_allow_drop_table(
    empty_db: tuple[str, str | None],
) -> None:
    """Extra table in DB; compare(allow_drop_table=True) has DROP; do_sync drops it;
    recompare 0 extra (01-functional: Opt-in flags)."""
    url, target_schema = empty_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE other_table (id INTEGER PRIMARY KEY)"))
        conn.commit()
    engine.dispose()

    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=target_schema)
    plan_or_err = sync.compare(SimpleTable, allow_drop_table=True)
    assert not isinstance(plan_or_err, modelsync.SyncError)
    # Plan: DROP TABLE other_table (extra) + CREATE TABLE simple_table (missing)
    assert len(plan_or_err.steps) >= 1
    drop_steps = [s for s in plan_or_err.steps if s.sql and "DROP TABLE" in s.sql]
    assert len(drop_steps) == 1
    assert "other_table" in (drop_steps[0].sql or "")

    result = sync.do_sync(SimpleTable, allow_drop_table=True)
    assert not isinstance(result, modelsync.SyncError)
    recompare = sync.compare(SimpleTable)
    assert not isinstance(recompare, modelsync.SyncError)
    assert len(recompare.extra_tables) == 0
    assert len(recompare.steps) == 0


def test_two_tables_one_missing_do_sync_both_present(
    empty_db: tuple[str, str | None],
) -> None:
    """Two tables in model; one missing. Plan CREATE missing; do_sync; recompare 0 steps."""
    url, target_schema = empty_db
    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=target_schema)
    sync.do_sync(SimpleTable)
    plan_or_err = sync.compare([SimpleTable, OtherTable])
    assert not isinstance(plan_or_err, modelsync.SyncError)
    assert len(plan_or_err.steps) == 1
    assert "other_table" in plan_or_err.sql()

    result = sync.do_sync([SimpleTable, OtherTable])
    assert not isinstance(result, modelsync.SyncError)
    recompare = sync.compare([SimpleTable, OtherTable])
    assert len(recompare.steps) == 0
