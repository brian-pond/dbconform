"""
Conform plan step types and ConformPlan container.

Each step has a description and SQL (or None for no-op/report-only).
See docs/requirements/01-functional.md (Plan and DDL order).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from dbconform.internal.objects import (
    ColumnDef,
    IndexDef,
    QualifiedName,
    TableDef,
    UniqueDef,
)


@dataclass(slots=True)
class ConformStep:
    """Single step in a conform plan (DDL or data op)."""

    description: str
    sql: str | None = None
    # Optional: for reporting or dialect to regenerate SQL
    payload: Any = None

    def __str__(self) -> str:
        return self.description


@dataclass(slots=True)
class CreateTableStep(ConformStep):
    """Create a table (columns + table-level constraints)."""

    table: TableDef = field(default_factory=lambda: TableDef(name=QualifiedName(None, "")))


@dataclass(slots=True)
class AlterTableStep(ConformStep):
    """Alter a table (add/alter column, add constraint, etc.)."""

    table_name: QualifiedName = field(default_factory=lambda: QualifiedName(schema=None, name=""))
    # When adding a column:
    column: ColumnDef | None = None
    # When adding unique/check:
    unique: UniqueDef | None = None


@dataclass(slots=True)
class CreateIndexStep(ConformStep):
    """Create an index."""

    index: IndexDef = field(
        default_factory=lambda: IndexDef(name="", column_names=(), unique=False)
    )
    table_name: QualifiedName = field(default_factory=lambda: QualifiedName(schema=None, name=""))


@dataclass(slots=True)
class DropTableStep(ConformStep):
    """Drop a table. Emitted only when allow_drop_table=True (01-functional: Opt-in flags)."""

    table_name: QualifiedName = field(default_factory=lambda: QualifiedName(schema=None, name=""))


@dataclass(slots=True)
class ConformPlan:
    """
    Ordered list of DDL and data-operation steps plus optional extra tables.

    steps: dependency-ordered steps to apply. extra_tables: tables present
    in DB but not in model (reported only; no DROP unless opt-in).
    """

    steps: list[ConformStep] = field(default_factory=list)
    extra_tables: list[QualifiedName] = field(default_factory=list)

    def __iter__(self) -> Iterator[ConformStep]:
        return iter(self.steps)

    def sql(self) -> str:
        """Return concatenated SQL of all steps (one statement per line)."""
        return "\n".join(s.sql for s in self.steps if s.sql is not None and s.sql.strip())

    def statements(self) -> list[str]:
        """Return list of SQL statements."""
        return [s.sql for s in self.steps if s.sql is not None and s.sql.strip()]
