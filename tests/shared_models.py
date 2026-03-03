"""
Shared test models used by unit and integration tests.

Schema-only (table structure); names avoid "record" (row) to avoid confusion.
Traceability: docs/requirements/01-functional.md — Model discovery, compare/conform.
"""

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel


class SimpleTable(SQLModel, table=True):
    """One table, four columns. Used to drive compare/conform in tests."""

    __tablename__ = "simple_table"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=255)
    value: float = Field()
    count: int = Field()


class SimpleTableWideName(SQLModel, table=True):
    """Same shape as SimpleTable but name VARCHAR(500). Table simple_table_wide."""

    __tablename__ = "simple_table_wide"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=500)
    value: float = Field()
    count: int = Field()


class SimpleTableWithUnique(SQLModel, table=True):
    """Same shape as SimpleTable but with a unique constraint on name (for apply-failure tests)."""

    __tablename__ = "simple_table_with_unique"
    __table_args__ = (UniqueConstraint("name", name="uq_simple_table_with_unique_name"),)

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=255)
    value: float = Field()
    count: int = Field()


class SimpleTableWithIndex(SQLModel, table=True):
    """Same shape as SimpleTable but with an index on name (for add-index integration test)."""

    __tablename__ = "simple_table_with_index"
    __table_args__ = (Index("idx_simple_table_with_index_name", "name"),)

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=255)
    value: float = Field()
    count: int = Field()


class OtherTable(SQLModel, table=True):
    """Second table for integration tests (e.g. two tables, one missing)."""

    __tablename__ = "other_table"

    id: int | None = Field(default=None, primary_key=True)
    label: str = Field(max_length=100)
