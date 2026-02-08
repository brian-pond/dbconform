"""
Shared test models used by unit and integration tests.

Schema-only (table structure); names avoid "record" (row) to avoid confusion.
Traceability: docs/requirements/01-functional.md — Model discovery, compare/sync.
"""

from sqlmodel import Field, SQLModel


class SimpleTable(SQLModel, table=True):
    """One table, four columns. Used to drive compare/sync in tests."""

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


class OtherTable(SQLModel, table=True):
    """Second table for integration tests (e.g. two tables, one missing)."""

    __tablename__ = "other_table"

    id: int | None = Field(default=None, primary_key=True)
    label: str = Field(max_length=100)
