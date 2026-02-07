"""
Extract canonical schema from SQLAlchemy or SQLModel model classes.

Callers pass a single model or sequence of models; we collect their Table
definitions and build a ModelSchema (name -> TableDef). See docs/requirements/01-functional.md
(Model discovery and API, Schema parity scope).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Table
from sqlalchemy.engine import Dialect
from sqlalchemy.schema import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from modelsync.schema.objects import (
    CheckDef,
    ColumnDef,
    ForeignKeyDef,
    IndexDef,
    PrimaryKeyDef,
    QualifiedName,
    TableDef,
    UniqueDef,
)


def _get_table_from_model(model: type) -> Table:
    """Return the SQLAlchemy Table for a declarative or SQLModel class."""
    table = getattr(model, "__table__", None)
    if table is None:
        raise TypeError(f"Model {model!r} has no __table__; not a mapped table class")
    if not isinstance(table, Table):
        raise TypeError(f"Model {model!r}.__table__ is not a Table: {type(table)}")
    return table


def _column_type_str(column: Any, dialect: Dialect) -> str:
    """Compile column type to a string for canonical comparison."""
    return column.type.compile(dialect=dialect)


def _default_expr(column: Any, _dialect: Dialect) -> str | None:
    """Return server default expression as string, or None."""
    default = getattr(column, "server_default", None) or getattr(
        column, "default", None
    )
    if default is None:
        return None
    if hasattr(default, "arg") and default.arg is not None:
        if callable(default.arg):
            return None  # Python-side default; no DDL expression
        return str(default.arg)
    if hasattr(default, "text") and default.text is not None:
        return default.text
    return None


def _extract_table_def(
    table: Table,
    dialect: Dialect,
    target_schema: str | None,
) -> TableDef:
    """Build a TableDef from a SQLAlchemy Table."""
    schema = table.schema if table.schema is not None else target_schema
    qualified_name = QualifiedName(schema=schema, name=table.name)

    columns: list[ColumnDef] = []
    for col in table.c:
        default = _default_expr(col, dialect)
        type_str = _column_type_str(col, dialect)
        comment = getattr(col, "comment", None)
        autoincrement = getattr(col, "autoincrement", False)
        if isinstance(autoincrement, str):
            autoincrement = autoincrement == "auto"
        columns.append(
            ColumnDef(
                name=col.name,
                type_expr=type_str,
                nullable=col.nullable,
                default=default,
                comment=comment,
                autoincrement=bool(autoincrement),
            )
        )

    primary_key: PrimaryKeyDef | None = None
    if table.primary_key and table.primary_key.columns:
        primary_key = PrimaryKeyDef(
            column_names=tuple(c.name for c in table.primary_key.columns)
        )

    unique_constraints: list[UniqueDef] = []
    foreign_keys: list[ForeignKeyDef] = []
    check_constraints: list[CheckDef] = []

    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint) and constraint is not table.primary_key:
            unique_constraints.append(
                UniqueDef(
                    name=constraint.name,
                    column_names=tuple(c.name for c in constraint.columns),
                )
            )
        elif isinstance(constraint, CheckConstraint):
            expression = str(constraint.sqltext)
            check_constraints.append(
                CheckDef(name=constraint.name, expression=expression)
            )
        elif isinstance(constraint, ForeignKeyConstraint):
            ref_col = next(iter(constraint.elements)).column
            ref_table = ref_col.table
            ref_schema = ref_table.schema if ref_table.schema is not None else target_schema
            ref_name = QualifiedName(schema=ref_schema, name=ref_table.name)
            foreign_keys.append(
                ForeignKeyDef(
                    name=constraint.name,
                    column_names=tuple(c.name for c in constraint.columns),
                    ref_table=ref_name,
                    ref_column_names=tuple(el.column.name for el in constraint.elements),
                )
            )

    indexes: list[IndexDef] = []
    for idx in table.indexes:
        indexes.append(
            IndexDef(
                name=idx.name or f"ix_{table.name}_{'_'.join(c.name for c in idx.columns)}",
                column_names=tuple(c.name for c in idx.columns),
                unique=idx.unique or False,
            )
        )

    comment = getattr(table, "comment", None)

    return TableDef(
        name=qualified_name,
        columns=tuple(columns),
        primary_key=primary_key,
        unique_constraints=tuple(unique_constraints),
        foreign_keys=tuple(foreign_keys),
        check_constraints=tuple(check_constraints),
        indexes=tuple(indexes),
        comment=comment,
    )


class ModelSchema:
    """
    Canonical schema derived from code models (SQLAlchemy/SQLModel).

    Tables are keyed by QualifiedName. Built by from_models().
    """

    def __init__(self) -> None:
        self._tables: dict[QualifiedName, TableDef] = {}

    @property
    def tables(self) -> dict[QualifiedName, TableDef]:
        """Tables keyed by qualified name."""
        return self._tables

    @classmethod
    def from_models(
        cls,
        models: type | Sequence[type],
        dialect: Dialect,
        target_schema: str | None = None,
    ) -> ModelSchema:
        """
        Build ModelSchema from one or more model classes.

        Each model must have __table__ (SQLAlchemy Table). Uses the given
        dialect to compile column types to strings. target_schema is used
        when table.schema is None (e.g. PostgreSQL default schema).
        """
        if isinstance(models, type):
            model_seq: Sequence[type] = (models,)
        else:
            model_seq = models
        instance = cls()
        for model in model_seq:
            table = _get_table_from_model(model)
            table_def = _extract_table_def(table, dialect, target_schema)
            instance._tables[table_def.name] = table_def
        return instance
