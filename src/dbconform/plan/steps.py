"""
Conform plan step types and ConformPlan container.

Each step has a description and SQL (or None for no-op/report-only).
See docs/requirements/01-functional.md (Plan and DDL order).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, TextIO
import sys

from dbconform.internal.objects import (
    ColumnDef,
    IndexDef,
    QualifiedName,
    TableDef,
    UniqueDef,
)


@dataclass(frozen=True, slots=True)
class SkippedStep:
    """
    Record of a step that was skipped (e.g. SQLite constraint add when rebuild disabled).

    description: human-readable step description (e.g. "Add check constraint on X")
    reason: why it was skipped (e.g. "SQLite does not support ADD CONSTRAINT; allow_sqlite_table_rebuild=False")
    table_name: table affected, if applicable.
    """

    description: str
    reason: str
    table_name: QualifiedName | None = None


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

    index: IndexDef = field(default_factory=lambda: IndexDef(name="", column_names=(), unique=False))
    table_name: QualifiedName = field(default_factory=lambda: QualifiedName(schema=None, name=""))


@dataclass(slots=True)
class DropTableStep(ConformStep):
    """Drop a table. Emitted only when allow_drop_extra_tables=True (01-functional: Opt-in flags)."""

    table_name: QualifiedName = field(default_factory=lambda: QualifiedName(schema=None, name=""))


@dataclass(slots=True)
class RebuildTableStep(ConformStep):
    """
    Rebuild an existing table (SQLite-only).

    SQLite does not support ALTER TABLE ADD CONSTRAINT for CHECK, UNIQUE, or FOREIGN KEY.
    This step creates a new table with the target schema, copies data, drops the old table,
    and renames the new one. sql is None; execution uses dialect-specific rebuild logic.
    See docs/requirements/01-functional.md (Schema parity scope, SQLite constraint rebuild).
    """

    table_name: QualifiedName = field(default_factory=lambda: QualifiedName(schema=None, name=""))
    target_table: TableDef = field(default_factory=lambda: TableDef(name=QualifiedName(None, "")))
    old_table: TableDef = field(default_factory=lambda: TableDef(name=QualifiedName(None, "")))


@dataclass(slots=True)
class ConformPlan:
    """
    Ordered list of DDL and data-operation steps plus optional extra tables.

    steps: dependency-ordered steps to apply. extra_tables: tables present
    in DB but not in model (reported only; no DROP unless opt-in).
    skipped_steps: steps that could not be applied (e.g. SQLite constraint add when
    allow_sqlite_table_rebuild=False); drift remains for these.
    """

    steps: list[ConformStep] = field(default_factory=list)
    extra_tables: list[QualifiedName] = field(default_factory=list)
    skipped_steps: list[SkippedStep] = field(default_factory=list)

    def __iter__(self) -> Iterator[ConformStep]:
        return iter(self.steps)

    def sql(self) -> str:
        """Return concatenated SQL of all steps (one statement per line)."""
        parts: list[str] = []
        for s in self.steps:
            if isinstance(s, RebuildTableStep):
                parts.append(f"-- Rebuild table {s.table_name} (SQLite: add constraints)")
            elif s.sql and s.sql.strip():
                parts.append(s.sql)
        return "\n".join(parts)

    def statements(self) -> list[str]:
        """Return list of SQL statements (excludes RebuildTableStep; use apply executor)."""
        return [s.sql for s in self.steps if s.sql is not None and s.sql.strip()]

    def summary(self) -> str:
        """
        Return a human-readable summary of the plan.

        Includes counts of steps, extra_tables, and skipped_steps, plus brief details
        for each section. See docs/requirements/01-functional.md (Plan and DDL order)
        and 02-non-functional.md (Observability).
        """
        lines: list[str] = []
        lines.append(
            f"ConformPlan: {len(self.steps)} steps, "
            f"{len(self.extra_tables)} extra tables, "
            f"{len(self.skipped_steps)} skipped steps"
        )
        if self.steps:
            lines.append("Steps:")
            for step in self.steps:
                lines.append(f"- {step.description}")
        if self.extra_tables:
            lines.append("Extra tables:")
            for name in self.extra_tables:
                lines.append(f"- {name}")
        if self.skipped_steps:
            lines.append("Skipped steps:")
            for s in self.skipped_steps:
                table = f" on {s.table_name}" if s.table_name is not None else ""
                lines.append(f"- {s.description}{table} (reason: {s.reason})")
        return "\n".join(lines)

    def print_summary(self, file: TextIO | None = None) -> None:
        """
        Pretty-print the plan summary to a file-like object (stdout by default).

        Convenience wrapper around summary() so callers can quickly inspect
        planned steps, extra tables, and skipped steps.
        """
        target = file if file is not None else sys.stdout
        target.write(self.summary() + "\n")
