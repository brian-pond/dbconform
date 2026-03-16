"""
Integration tests: column add/remove (missing column, extra column, combinations).

Traceability: docs/requirements/01-functional.md — Schema parity, add/alter only (no DROP column).
Pattern: create table, compare to SimpleTable, assert plan, apply_changes or no-op, recompare.
"""

from sqlalchemy import create_engine, text

import dbconform
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


def test_one_column_missing_in_db_apply_changes_then_parity(empty_db: tuple[str, str | None]) -> None:
    """Scenario 4: One column missing in DB. Plan has one ADD COLUMN; apply_changes; recompare 0 steps."""
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

    conform = dbconform.DbConform(credentials={"url": url}, target_schema=target_schema)
    plan_or_err = conform.compare(SimpleTable)
    assert not isinstance(plan_or_err, dbconform.ConformError)
    assert len(plan_or_err.steps) == 1
    assert "ADD COLUMN" in plan_or_err.sql() and "value" in plan_or_err.sql()

    result = conform.apply_changes(SimpleTable)
    assert not isinstance(result, dbconform.ConformError)
    recompare = conform.compare(SimpleTable)
    assert len(recompare.steps) == 0


def test_multiple_columns_missing_in_db_apply_changes_then_parity(
    empty_db: tuple[str, str | None],
) -> None:
    """Multiple columns missing. Plan has ADD COLUMN each; apply_changes; recompare 0 steps."""
    url, target_schema = empty_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE simple_table (id INTEGER PRIMARY KEY, name VARCHAR(255) NOT NULL)"))
        conn.commit()
    engine.dispose()

    conform = dbconform.DbConform(credentials={"url": url}, target_schema=target_schema)
    plan_or_err = conform.compare(SimpleTable)
    assert not isinstance(plan_or_err, dbconform.ConformError)
    assert len(plan_or_err.steps) == 2
    add_sql = plan_or_err.sql()
    assert "value" in add_sql and "count" in add_sql

    result = conform.apply_changes(SimpleTable)
    assert not isinstance(result, dbconform.ConformError)
    recompare = conform.compare(SimpleTable)
    assert len(recompare.steps) == 0


def test_one_extra_column_in_db_no_drop_recompare_still_different(
    empty_db: tuple[str, str | None],
) -> None:
    """One extra column in DB. No DROP; apply_changes no-op; recompare still shows difference.
    
    Traceability: docs/requirements/01-functional.md (Opt-in flags, allow_drop_extra_columns).
    Extra columns require opt-in; when blocked, drift is recorded in skipped_steps.
    """
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

    conform = dbconform.DbConform(credentials={"url": url}, target_schema=target_schema)
    plan_or_err = conform.compare(SimpleTable)
    assert not isinstance(plan_or_err, dbconform.ConformError)
    assert not any("DROP" in (s.sql or "") for s in plan_or_err.steps)
    assert len(plan_or_err.steps) == 0
    # Extra column should be recorded in skipped_steps
    assert len(plan_or_err.skipped_steps) == 1
    assert "extra_col" in plan_or_err.skipped_steps[0].description
    assert "allow_drop_extra_columns=False" in plan_or_err.skipped_steps[0].reason

    conform.apply_changes(SimpleTable)
    recompare = conform.compare(SimpleTable)
    assert len(recompare.steps) == 0
    assert len(recompare.skipped_steps) == 1  # Still skipped after apply
    col_names = _table_column_names(url, "simple_table", target_schema)
    assert "extra_col" in col_names


def test_multiple_extra_columns_in_db_no_drop(empty_db: tuple[str, str | None]) -> None:
    """Multiple extra columns in DB. No DROP; recompare still has extra columns.
    
    Traceability: docs/requirements/01-functional.md (Opt-in flags).
    Multiple extra columns all recorded in skipped_steps.
    """
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

    conform = dbconform.DbConform(credentials={"url": url}, target_schema=target_schema)
    plan_or_err = conform.compare(SimpleTable)
    assert not isinstance(plan_or_err, dbconform.ConformError)
    assert len(plan_or_err.steps) == 0
    assert not any("DROP" in (s.sql or "") for s in plan_or_err.steps)
    # Both extra columns should be in skipped_steps
    assert len(plan_or_err.skipped_steps) == 2
    descriptions = [s.description for s in plan_or_err.skipped_steps]
    assert any("a" in d for d in descriptions)
    assert any("b" in d for d in descriptions)

    conform.apply_changes(SimpleTable)
    recompare = conform.compare(SimpleTable)
    assert len(recompare.steps) == 0
    assert len(recompare.skipped_steps) == 2


def test_one_missing_one_extra_add_only_extra_remains(
    empty_db: tuple[str, str | None],
) -> None:
    """One missing, one extra. Plan ADD only; apply_changes; extra column still present.
    
    Traceability: docs/requirements/01-functional.md (add/alter by default, drops require opt-in).
    Extra column in skipped_steps; missing column in steps.
    """
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

    conform = dbconform.DbConform(credentials={"url": url}, target_schema=target_schema)
    plan_or_err = conform.compare(SimpleTable)
    assert not isinstance(plan_or_err, dbconform.ConformError)
    assert len(plan_or_err.steps) == 1
    assert "value" in plan_or_err.sql()
    assert "DROP" not in plan_or_err.sql()
    # Extra column in skipped_steps
    assert len(plan_or_err.skipped_steps) == 1
    assert "extra_col" in plan_or_err.skipped_steps[0].description

    result = conform.apply_changes(SimpleTable)
    assert not isinstance(result, dbconform.ConformError)
    recompare = conform.compare(SimpleTable)
    assert len(recompare.steps) == 0
    assert len(recompare.skipped_steps) == 1  # Extra column still skipped
    col_names = _table_column_names(url, "simple_table", target_schema)
    assert "extra_col" in col_names


def test_extra_column_dropped_when_allow_drop_extra_columns(
    empty_db: tuple[str, str | None],
) -> None:
    """Extra column in DB. DROP COLUMN when allow_drop_extra_columns=True; then parity.
    
    Traceability: docs/requirements/01-functional.md (Opt-in flags, allow_drop_extra_columns).
    When opt-in is enabled, extra columns are dropped and parity is achieved.
    """
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

    conform = dbconform.DbConform(credentials={"url": url}, target_schema=target_schema)
    plan_or_err = conform.compare(SimpleTable, allow_drop_extra_columns=True)
    assert not isinstance(plan_or_err, dbconform.ConformError)
    assert len(plan_or_err.steps) == 1
    assert "DROP COLUMN" in plan_or_err.sql()
    assert "extra_col" in plan_or_err.sql()
    assert len(plan_or_err.skipped_steps) == 0  # Not skipped when allowed

    result = conform.apply_changes(SimpleTable, allow_drop_extra_columns=True)
    assert not isinstance(result, dbconform.ConformError)
    
    # After apply, column should be gone
    col_names = _table_column_names(url, "simple_table", target_schema)
    assert "extra_col" not in col_names
    
    # Recompare should show parity
    recompare = conform.compare(SimpleTable)
    assert len(recompare.steps) == 0
    assert len(recompare.skipped_steps) == 0
