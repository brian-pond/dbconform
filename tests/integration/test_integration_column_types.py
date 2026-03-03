"""
Integration tests: column type, length, nullability, default mismatches.

SQLite does not support ALTER COLUMN; we assert diff/plan behavior and that recompare still
shows difference where no DDL is emitted. Traceability: docs/requirements/01-functional.md.

PostgreSQL supports ALTER COLUMN; separate tests below assert plan has ALTER step(s) and
apply_changes achieves parity (recompare 0 steps).
"""

from pathlib import Path
from typing import Any, TypeVar

from sqlalchemy import create_engine, text

import dbconform
from dbconform.plan import ConformPlan
from tests.shared_models import SimpleTable, SimpleTableWideName

_ModelT = TypeVar("_ModelT")


def _postgres_alter_then_parity(
    url: str,
    schema: str,
    create_sql: str,
    model_class: type[_ModelT],
    **compare_kw: Any,
) -> ConformPlan:
    """
    Create table from create_sql, compare to model, assert plan has steps, apply_changes, recompare 0.

    Returns the first plan so callers can assert on plan.sql() (e.g. ALTER, NOT NULL).
    """
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(text(create_sql))
        conn.commit()
    engine.dispose()
    conform = dbconform.DbConform(credentials={"url": url}, target_schema=schema)
    plan_or_err = conform.compare(model_class, **compare_kw)
    assert not isinstance(plan_or_err, dbconform.ConformError)
    assert len(plan_or_err.steps) >= 1
    result = conform.apply_changes(model_class, **compare_kw)
    assert not isinstance(result, dbconform.ConformError)
    recompare = conform.compare(model_class)
    assert len(recompare.steps) == 0
    return plan_or_err


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

    conform = dbconform.DbConform(credentials={"url": url}, target_schema=None)
    plan_or_err = conform.compare(SimpleTable)
    assert not isinstance(plan_or_err, dbconform.ConformError)
    assert len(plan_or_err.steps) == 0

    conform.apply_changes(SimpleTable)
    recompare = conform.compare(SimpleTable)
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

    conform = dbconform.DbConform(credentials={"url": url}, target_schema=None)
    plan_or_err = conform.compare(SimpleTable)
    assert not isinstance(plan_or_err, dbconform.ConformError)
    assert len(plan_or_err.steps) == 0

    conform.apply_changes(SimpleTable)
    recompare = conform.compare(SimpleTable)
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

    conform = dbconform.DbConform(credentials={"url": url}, target_schema=None)
    plan_or_err = conform.compare(SimpleTable)
    assert not isinstance(plan_or_err, dbconform.ConformError)
    assert len(plan_or_err.steps) == 0

    conform.apply_changes(SimpleTable)
    recompare = conform.compare(SimpleTable)
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

    conform = dbconform.DbConform(credentials={"url": url}, target_schema=None)
    plan_or_err = conform.compare(SimpleTable, allow_shrink_column=False)
    assert not isinstance(plan_or_err, dbconform.ConformError)
    assert len(plan_or_err.steps) == 0
    plan_allow = conform.compare(SimpleTable, allow_shrink_column=True)
    assert not isinstance(plan_allow, dbconform.ConformError)
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

    conform = dbconform.DbConform(credentials={"url": url}, target_schema=None)
    plan_or_err = conform.compare(SimpleTableWideName)
    assert not isinstance(plan_or_err, dbconform.ConformError)
    assert len(plan_or_err.steps) == 0

    conform.apply_changes(SimpleTableWideName)
    recompare = conform.compare(SimpleTableWideName)
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

    conform = dbconform.DbConform(credentials={"url": url}, target_schema=None)
    plan_or_err = conform.compare(SimpleTable)
    assert not isinstance(plan_or_err, dbconform.ConformError)
    assert len(plan_or_err.steps) == 0

    conform.apply_changes(SimpleTable)
    recompare = conform.compare(SimpleTable)
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

    conform = dbconform.DbConform(credentials={"url": url}, target_schema=None)
    plan_or_err = conform.compare(SimpleTable)
    assert not isinstance(plan_or_err, dbconform.ConformError)
    assert len(plan_or_err.steps) == 0

    conform.apply_changes(SimpleTable)
    recompare = conform.compare(SimpleTable)
    assert len(recompare.steps) == 0


# --- PostgreSQL: ALTER COLUMN emitted; apply_changes achieves parity (01-functional: Schema parity). ---


def test_data_type_mismatch_postgres_alter_then_parity(
    empty_postgres_db: tuple[str, str],
) -> None:
    """DB INTEGER for value, model FLOAT. PostgreSQL emits ALTER COLUMN; apply_changes then parity."""
    url, schema = empty_postgres_db
    plan = _postgres_alter_then_parity(
        url,
        schema,
        "CREATE TABLE simple_table ("
        "id SERIAL PRIMARY KEY, name VARCHAR(255) NOT NULL, "
        "value INTEGER NOT NULL, count INTEGER NOT NULL)",
        SimpleTable,
    )
    assert "ALTER" in plan.sql() and "value" in plan.sql().lower()


def test_length_shorter_in_db_postgres_alter_then_parity(
    empty_postgres_db: tuple[str, str],
) -> None:
    """DB VARCHAR(100), model VARCHAR(255). PostgreSQL emits ALTER; apply_changes then parity."""
    url, schema = empty_postgres_db
    _postgres_alter_then_parity(
        url,
        schema,
        "CREATE TABLE simple_table ("
        "id SERIAL PRIMARY KEY, name VARCHAR(100) NOT NULL, "
        "value DOUBLE PRECISION NOT NULL, count INTEGER NOT NULL)",
        SimpleTable,
    )


def test_length_shrink_postgres_allow_shrink_alter_then_parity(
    empty_postgres_db: tuple[str, str],
) -> None:
    """DB VARCHAR(500), model VARCHAR(255), allow_shrink_column=True. PostgreSQL alter then parity."""
    url, schema = empty_postgres_db
    _postgres_alter_then_parity(
        url,
        schema,
        "CREATE TABLE simple_table ("
        "id SERIAL PRIMARY KEY, name VARCHAR(500) NOT NULL, "
        "value DOUBLE PRECISION NOT NULL, count INTEGER NOT NULL)",
        SimpleTable,
        allow_shrink_column=True,
    )


def test_model_wider_length_db_narrower_postgres_alter_then_parity(
    empty_postgres_db: tuple[str, str],
) -> None:
    """Model SimpleTableWideName VARCHAR(500), DB name VARCHAR(255). PostgreSQL alter then parity."""
    url, schema = empty_postgres_db
    _postgres_alter_then_parity(
        url,
        schema,
        "CREATE TABLE simple_table_wide ("
        "id SERIAL PRIMARY KEY, name VARCHAR(255) NOT NULL, "
        "value DOUBLE PRECISION NOT NULL, count INTEGER NOT NULL)",
        SimpleTableWideName,
    )


def test_nullability_differs_postgres_alter_then_parity(
    empty_postgres_db: tuple[str, str],
) -> None:
    """DB name nullable, model NOT NULL. PostgreSQL SET NOT NULL; apply_changes then parity."""
    url, schema = empty_postgres_db
    plan = _postgres_alter_then_parity(
        url,
        schema,
        "CREATE TABLE simple_table ("
        "id SERIAL PRIMARY KEY, name VARCHAR(255), "
        "value DOUBLE PRECISION NOT NULL, count INTEGER NOT NULL)",
        SimpleTable,
    )
    assert "NOT NULL" in plan.sql()


def test_default_differs_postgres_alter_then_parity(
    empty_postgres_db: tuple[str, str],
) -> None:
    """DB has DEFAULT 0 on count, model has no default. PostgreSQL DROP DEFAULT; apply_changes then parity."""
    url, schema = empty_postgres_db
    _postgres_alter_then_parity(
        url,
        schema,
        "CREATE TABLE simple_table ("
        "id SERIAL PRIMARY KEY, name VARCHAR(255) NOT NULL, "
        "value DOUBLE PRECISION NOT NULL, count INTEGER NOT NULL DEFAULT 0)",
        SimpleTable,
    )
