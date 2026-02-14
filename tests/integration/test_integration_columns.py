"""
Integration tests: column add/remove (missing column, extra column, combinations).

Traceability: docs/requirements/01-functional.md — Schema parity, add/alter only (no DROP column).
Pattern: create table, compare to SimpleTable, assert plan, do_sync or no-op, recompare.
"""

from sqlalchemy import create_engine, text

import modelsync
from tests.shared_models import SimpleTable


def _table_column_names(url: str, table_name: str, schema: str | None) -> list[str]:
    """Return column names for table (backend-agnostic)."""
    engine = create_engine(url)
    with engine.connect() as conn:
        if conn.dialect.name == "sqlite":
            r = conn.execute(text(f"PRAGMA table_info({table_name})"))
            return [row[1] for row in r]
        schema = schema or "public"
        r = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = :t ORDER BY ordinal_position"
            ),
            {"schema": schema, "t": table_name},
        )
        return [row[0] for row in r]


def test_one_column_missing_in_db_do_sync_then_parity(empty_db: tuple[str, str | None]) -> None:
    """Scenario 4: One column missing in DB. Plan has one ADD COLUMN; do_sync; recompare 0 steps."""
    url, target_schema = empty_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE simple_table ("
                "id INTEGER PRIMARY KEY, name VARCHAR(255) NOT NULL, "
                "count INTEGER NOT NULL)"
            )
        )
        conn.commit()
    engine.dispose()

    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=target_schema)
    plan_or_err = sync.compare(SimpleTable)
    assert not isinstance(plan_or_err, modelsync.SyncError)
    assert len(plan_or_err.steps) == 1
    assert "ADD COLUMN" in plan_or_err.sql() and "value" in plan_or_err.sql()

    result = sync.do_sync(SimpleTable)
    assert not isinstance(result, modelsync.SyncError)
    recompare = sync.compare(SimpleTable)
    assert len(recompare.steps) == 0


def test_multiple_columns_missing_in_db_do_sync_then_parity(
    empty_db: tuple[str, str | None],
) -> None:
    """Multiple columns missing. Plan has ADD COLUMN each; do_sync; recompare 0 steps."""
    url, target_schema = empty_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text("CREATE TABLE simple_table (id INTEGER PRIMARY KEY, name VARCHAR(255) NOT NULL)")
        )
        conn.commit()
    engine.dispose()

    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=target_schema)
    plan_or_err = sync.compare(SimpleTable)
    assert not isinstance(plan_or_err, modelsync.SyncError)
    assert len(plan_or_err.steps) == 2
    add_sql = plan_or_err.sql()
    assert "value" in add_sql and "count" in add_sql

    result = sync.do_sync(SimpleTable)
    assert not isinstance(result, modelsync.SyncError)
    recompare = sync.compare(SimpleTable)
    assert len(recompare.steps) == 0


def test_one_extra_column_in_db_no_drop_recompare_still_different(
    empty_db: tuple[str, str | None],
) -> None:
    """One extra column in DB. No DROP; do_sync no-op; recompare still shows difference."""
    url, target_schema = empty_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE simple_table ("
                "id INTEGER PRIMARY KEY, name VARCHAR(255) NOT NULL, "
                "value FLOAT NOT NULL, count INTEGER NOT NULL, extra_col TEXT)"
            )
        )
        conn.commit()
    engine.dispose()

    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=target_schema)
    plan_or_err = sync.compare(SimpleTable)
    assert not isinstance(plan_or_err, modelsync.SyncError)
    assert not any("DROP" in (s.sql or "") for s in plan_or_err.steps)
    assert len(plan_or_err.steps) == 0

    sync.do_sync(SimpleTable)
    recompare = sync.compare(SimpleTable)
    assert len(recompare.steps) == 0
    col_names = _table_column_names(url, "simple_table", target_schema)
    assert "extra_col" in col_names


def test_multiple_extra_columns_in_db_no_drop(empty_db: tuple[str, str | None]) -> None:
    """Multiple extra columns in DB. No DROP; recompare still has extra columns."""
    url, target_schema = empty_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE simple_table ("
                "id INTEGER PRIMARY KEY, name VARCHAR(255) NOT NULL, "
                "value FLOAT NOT NULL, count INTEGER NOT NULL, a TEXT, b INTEGER)"
            )
        )
        conn.commit()
    engine.dispose()

    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=target_schema)
    plan_or_err = sync.compare(SimpleTable)
    assert not isinstance(plan_or_err, modelsync.SyncError)
    assert len(plan_or_err.steps) == 0
    assert not any("DROP" in (s.sql or "") for s in plan_or_err.steps)

    sync.do_sync(SimpleTable)
    recompare = sync.compare(SimpleTable)
    assert len(recompare.steps) == 0


def test_one_missing_one_extra_add_only_extra_remains(
    empty_db: tuple[str, str | None],
) -> None:
    """One missing, one extra. Plan ADD only; do_sync; extra column still present."""
    url, target_schema = empty_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE simple_table ("
                "id INTEGER PRIMARY KEY, name VARCHAR(255) NOT NULL, "
                "count INTEGER NOT NULL, extra_col TEXT)"
            )
        )
        conn.commit()
    engine.dispose()

    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=target_schema)
    plan_or_err = sync.compare(SimpleTable)
    assert not isinstance(plan_or_err, modelsync.SyncError)
    assert len(plan_or_err.steps) == 1
    assert "value" in plan_or_err.sql()
    assert "DROP" not in plan_or_err.sql()

    result = sync.do_sync(SimpleTable)
    assert not isinstance(result, modelsync.SyncError)
    recompare = sync.compare(SimpleTable)
    assert len(recompare.steps) == 0
    col_names = _table_column_names(url, "simple_table", target_schema)
    assert "extra_col" in col_names
