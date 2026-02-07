"""
Canonical schema object definitions for diff and DDL generation.

These types represent tables, columns, and constraints in a dialect-agnostic
form so ModelSchema and DatabaseSchema can be compared. See docs/requirements/01-functional.md
(Schema parity scope) and docs/technical/02-architecture.md.

BR: Schema parity — tables, columns, primary keys, unique, foreign keys, indexes, check constraints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QualifiedName:
    """
    Schema-qualified identifier for a table or other object.

    For SQLite, schema is None. For PostgreSQL/MariaDB, schema is the
    target schema (e.g. 'public'). Used as key for table identity in diff.
    """

    schema: str | None
    name: str

    def __str__(self) -> str:
        if self.schema is None:
            return self.name
        return f"{self.schema}.{self.name}"

    def with_schema(self, schema: str | None) -> QualifiedName:
        """Return a new QualifiedName with the given schema."""
        return QualifiedName(schema=schema, name=self.name)


@dataclass(frozen=True)
class ColumnDef:
    """
    Canonical column definition.

    type_expr: dialect-agnostic type string (e.g. 'INTEGER', 'VARCHAR(255)')
    for comparison; dialect modules produce backend-specific DDL.
    """

    name: str
    type_expr: str
    nullable: bool = True
    default: str | None = None
    comment: str | None = None
    # For PK identity / autoincrement; dialect-specific representation
    autoincrement: bool = False

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, ColumnDef):
            return NotImplemented
        return (
            self.name == other.name
            and self.type_expr == other.type_expr
            and self.nullable == other.nullable
            and self.default == other.default
            and self.comment == other.comment
            and self.autoincrement == other.autoincrement
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.name,
                self.type_expr,
                self.nullable,
                self.default,
                self.comment,
                self.autoincrement,
            )
        )


@dataclass(frozen=True)
class PrimaryKeyDef:
    """Primary key constraint: table + ordered column names."""

    column_names: tuple[str, ...]


@dataclass(frozen=True)
class UniqueDef:
    """Unique constraint: optional name + column names."""

    name: str | None
    column_names: tuple[str, ...]


@dataclass(frozen=True)
class ForeignKeyDef:
    """Foreign key: columns on this table referencing another table's columns."""

    name: str | None
    column_names: tuple[str, ...]
    ref_table: QualifiedName
    ref_column_names: tuple[str, ...]


@dataclass(frozen=True)
class CheckDef:
    """Check constraint: name + SQL expression (dialect-specific)."""

    name: str | None
    expression: str


@dataclass(frozen=True)
class IndexDef:
    """Index: name + columns + unique flag."""

    name: str
    column_names: tuple[str, ...]
    unique: bool = False


@dataclass(frozen=True)
class TableDef:
    """
    Canonical table definition for diff and DDL.

    Columns are ordered by definition order. Constraints and indexes
    are collected for dependency-aware DDL ordering. Comments per
    docs/requirements/01-functional.md (table and column comments).
    """

    name: QualifiedName
    columns: tuple[ColumnDef, ...] = ()
    primary_key: PrimaryKeyDef | None = None
    unique_constraints: tuple[UniqueDef, ...] = ()
    foreign_keys: tuple[ForeignKeyDef, ...] = ()
    check_constraints: tuple[CheckDef, ...] = ()
    indexes: tuple[IndexDef, ...] = ()
    comment: str | None = None

    def column_by_name(self) -> dict[str, ColumnDef]:
        """Return a dict of column name -> ColumnDef for lookup."""
        return {c.name: c for c in self.columns}
