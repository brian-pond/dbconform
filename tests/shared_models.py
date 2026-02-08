"""
Shared test models used by unit and integration tests.

Traceability: docs/requirements/01-functional.md — Model discovery, compare/sync.
"""

from sqlmodel import Field, SQLModel


class SimpleRecord(SQLModel, table=True):
    """One table, three columns. Used to drive compare/sync in tests."""

    __tablename__ = "simple_record"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=255)
    value: float = Field()
    count: int = Field()
