"""
Build internal schema from SQLAlchemy or SQLModel model classes.

Callers pass a single model or sequence of models; we collect their Table
definitions and build a ModelSchema (name -> TableDef). See docs/requirements/01-functional.md
(Model discovery and API, Schema parity scope).

**Read-only contract:** Ingestion does not mutate caller models. We only read from
model.__table__ and its columns/constraints/indexes; we never assign to or modify
the caller's Table or column objects. ModelSchema stores only internal TableDef
instances, not references to the original tables.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from sqlalchemy import Table
from sqlalchemy.engine import Dialect
from sqlalchemy.schema import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from modelsync.adapters.sa_to_neutral import sa_column_to_neutral_type
from modelsync.internal.objects import (
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


def _column_type_str(column: Any, dialect: Dialect | None) -> str:
    """Return neutral type string for internal schema (dialect=None) or compiled type (dialect set)."""
    if dialect is None:
        return sa_column_to_neutral_type(column)
    return column.type.compile(dialect=dialect)


def _default_expr(column: Any, _dialect: Dialect) -> str | None:
    """Return server default expression as string, or None."""
    default = getattr(column, "server_default", None) or getattr(column, "default", None)
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
    target_schema: str | None,
    dialect: Dialect | None = None,
) -> TableDef:
    """Build a TableDef from a SQLAlchemy Table. When dialect is None, use neutral type names."""
    schema = table.schema if table.schema is not None else target_schema
    qualified_name = QualifiedName(schema=schema, name=table.name)

    columns: list[ColumnDef] = []
    # Only the single integer PK column should have autoincrement=True (SA uses "auto" on others too).
    is_single_pk = (
        table.primary_key
        and len(table.primary_key.columns) == 1
    )
    pk_col_name = (
        list(table.primary_key.columns)[0].name
        if is_single_pk
        else None
    )
    _integer_type_names = ("Integer", "INTEGER", "BigInteger", "BIGINT", "SmallInteger", "SMALLINT")
    for col in table.c:
        default = _default_expr(col, dialect)
        type_str = _column_type_str(col, dialect)
        comment = getattr(col, "comment", None)
        sa_auto = getattr(col, "autoincrement", False)
        if isinstance(sa_auto, str):
            sa_auto = sa_auto == "auto"
        is_pk_col = pk_col_name is not None and col.name == pk_col_name
        is_integer = type(col.type).__name__ in _integer_type_names
        autoincrement = bool(
            is_single_pk and is_pk_col and is_integer and sa_auto
        )
        columns.append(
            ColumnDef(
                name=col.name,
                data_type_name=type_str,
                nullable=col.nullable,
                default=default,
                comment=comment,
                autoincrement=autoincrement,
            )
        )

    primary_key: PrimaryKeyDef | None = None
    if table.primary_key and table.primary_key.columns:
        primary_key = PrimaryKeyDef(column_names=tuple(c.name for c in table.primary_key.columns))

    unique_constraints: list[UniqueDef] = []
    foreign_keys: list[ForeignKeyDef] = []
    check_constraints: list[CheckDef] = []

    for constraint in table.constraints:
        match constraint:
            case UniqueConstraint() if constraint is not table.primary_key:
                unique_constraints.append(
                    UniqueDef(
                        name=constraint.name,
                        column_names=tuple(c.name for c in constraint.columns),
                    )
                )
            case CheckConstraint():
                expression = str(constraint.sqltext)
                check_constraints.append(CheckDef(name=constraint.name, expression=expression))
            case ForeignKeyConstraint():
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


class _SchemaNormalizer(Protocol):
    """Protocol for normalizing a TableDef so it compares equal across backends."""

    def normalize_reflected_table(self, table_def: TableDef) -> TableDef: ...


class ModelSchema:
    """
    Internal schema derived from code models (SQLAlchemy/SQLModel).

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
        target_schema: str | None = None,
        *,
        schema_normalizer: _SchemaNormalizer | None = None,
    ) -> ModelSchema:
        """
        Build ModelSchema from one or more model classes.

        Each model must have __table__ (SQLAlchemy Table). Column types are
        mapped to neutral type names (no target database). target_schema is
        used when table.schema is None (e.g. PostgreSQL default schema).
        If schema_normalizer is provided (e.g. modelsync Dialect), its
        normalize_reflected_table is applied so model-side internal schema compares equal to database-side internal schema.
        """
        if isinstance(models, type):
            model_seq: Sequence[type] = (models,)
        else:
            model_seq = models
        instance = cls()
        for model in model_seq:
            table = _get_table_from_model(model)
            table_def = _extract_table_def(table, target_schema, dialect=None)
            if schema_normalizer is not None:
                table_def = schema_normalizer.normalize_reflected_table(table_def)
            instance._tables[table_def.name] = table_def
        return instance
