"""
First test: simple one-table model and intended compare() usage.

Traceability: docs/requirements/01-functional.md — Model discovery and API,
Database connection, compare() / do_sync(). Acceptance: schema (create tables, columns).
"""

from pathlib import Path

import pytest
from sqlmodel import SQLModel, Field


# --- Simple data model: one table, 3 columns (string, float, integer) ---
class SimpleRecord(SQLModel, table=True):
    """One table, three columns. Used to drive compare/sync once modelsync exists."""

    __tablename__ = "simple_record"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=255)
    value: float = Field()
    count: int = Field()


# --- Pseudocode: how we would pass Model + Credentials and ask for a comparison ---
#
#   import modelsync
#
#   # Option A: pass credentials; modelsync opens connection, runs compare, closes
#   credentials = {"url": "sqlite:///./test.db"}  # or postgres/mariadb URL + schema
#   target_schema = None  # or "public" for PostgreSQL
#
#   sync = modelsync.ModelSync(credentials=credentials, target_schema=target_schema)
#   plan = sync.compare(SimpleRecord)   # single model
#   # plan = sync.compare([SimpleRecord, OtherModel, ...])  # or sequence of models
#
#   # Option B: pass an existing connection (caller manages lifecycle)
#   # engine = create_engine(...)
#   # with engine.connect() as conn:
#   #     sync = modelsync.ModelSync(connection=conn, target_schema=target_schema)
#   #     plan = sync.compare(SimpleRecord)
#
#   # plan is a list of DDL and data-operation steps (no apply yet; apply=False by default)
#   # On failure, sync returns a structured Error object: which objects failed and why.
#
# --- End pseudocode ---


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
