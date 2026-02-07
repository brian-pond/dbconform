"""
First test: simple one-table model and intended compare() usage.

Traceability: docs/requirements/01-functional.md — Model discovery and API,
Database connection, compare() / do_sync(). Acceptance: schema (create tables, columns).
"""

from pathlib import Path

from sqlmodel import Field, SQLModel


# --- Simple data model: one table, 3 columns (string, float, integer) ---
class SimpleRecord(SQLModel, table=True):
    """One table, three columns. Used to drive compare/sync once modelsync exists."""

    __tablename__ = "simple_record"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=255)
    value: float = Field()
    count: int = Field()


# --- ModelSync usage (01-functional: Model discovery, Database connection) ---
# Option A: credentials — modelsync opens connection, runs compare, closes.
# Option B: connection — caller manages lifecycle.
# compare() returns SyncPlan (steps + optional extra_tables) or SyncError on failure.


def test_simple_model_has_expected_columns() -> None:
    """Verify the simple model defines one table with string, float, and integer columns."""
    # Until modelsync.compare() exists, we assert the fixture model is valid for use.
    assert SimpleRecord.__tablename__ == "simple_record"
    assert hasattr(SimpleRecord, "id") and hasattr(SimpleRecord, "name")
    assert hasattr(SimpleRecord, "value") and hasattr(SimpleRecord, "count")
    from typing import get_type_hints
    hints = get_type_hints(SimpleRecord)
    assert hints["name"] is str
    assert hints["value"] is float
    assert hints["count"] is int


def test_empty_sqlite_db_fixture(empty_sqlite_db: tuple[Path, str]) -> None:
    """Use empty_sqlite_db fixture: DB exists, is writable, and can have tables created."""
    from sqlalchemy import create_engine, text

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
    import modelsync

    _path, url = empty_sqlite_db
    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)
    result = sync.compare(SimpleRecord)
    assert not isinstance(result, modelsync.SyncError), str(result)
    plan = result
    assert len(plan.steps) == 1
    assert "simple_record" in plan.sql()
    assert "CREATE TABLE" in plan.sql()


def test_compare_with_connection(empty_sqlite_db: tuple[Path, str]) -> None:
    """Caller passes connection; compare returns plan (01-functional: pass existing connection)."""
    from sqlalchemy import create_engine

    import modelsync

    _path, url = empty_sqlite_db
    engine = create_engine(url)
    with engine.connect() as conn:
        sync = modelsync.ModelSync(connection=conn, target_schema=None)
        result = sync.compare(SimpleRecord)
    engine.dispose()
    assert not isinstance(result, modelsync.SyncError)
    assert len(result.steps) == 1


def test_compare_after_create_same_schema_no_steps(empty_sqlite_db: tuple[Path, str]) -> None:
    """Scenario 3: table exists in DB and matches model — no steps (schema parity)."""
    from sqlalchemy import create_engine, text

    import modelsync

    _path, url = empty_sqlite_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE simple_record "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(255) NOT NULL, "
                "value FLOAT NOT NULL, count INTEGER NOT NULL)"
            )
        )
        conn.commit()
    with engine.connect() as conn:
        sync = modelsync.ModelSync(connection=conn, target_schema=None)
        result = sync.compare(SimpleRecord)
    engine.dispose()
    assert not isinstance(result, modelsync.SyncError)
    assert len(result.steps) == 0


def test_compare_extra_table_in_db_reported_not_dropped(empty_sqlite_db: tuple[Path, str]) -> None:
    """Scenario 2: DB has table not in model — reported in extra_tables, no DROP (01-functional)."""
    from sqlalchemy import create_engine, text

    import modelsync

    _path, url = empty_sqlite_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE other_table (id INTEGER PRIMARY KEY)"))
        conn.commit()
    with engine.connect() as conn:
        sync = modelsync.ModelSync(connection=conn, target_schema=None)
        result = sync.compare(SimpleRecord)
    engine.dispose()
    assert not isinstance(result, modelsync.SyncError)
    assert len(result.extra_tables) == 1
    assert result.extra_tables[0].name == "other_table"
    assert not any("DROP" in (s.sql or "") for s in result.steps)
