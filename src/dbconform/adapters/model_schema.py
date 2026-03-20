"""
Build internal schema from SQLAlchemy or SQLModel model classes.

Callers pass a single model or sequence of models; we collect their Table
definitions and build a ModelSchema (name -> TableDef). See docs/requirements/01-functional.md
(Model discovery and API, Schema parity scope).

**Read-only contract:** Ingestion does not mutate caller models. We only read from
model.__table__ and its columns/constraints/indexes; we never assign to or modify
the caller's Table or column objects. ModelSchema stores only internal TableDef
instances, not references to the original tables.

**Column defaults:** How Python and server defaults become DDL strings (including the
PostgreSQL date-literal pitfall) is documented in docs/technical/05-model-column-defaults.md.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import Table
from sqlalchemy.engine import Dialect
from sqlalchemy.schema import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.sql.elements import ClauseElement

from dbconform.adapters.sa_to_neutral import sa_column_to_neutral_type
from dbconform.internal.objects import (
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


def _check_expression_str(sqltext: Any) -> str:
    """
    Compile CHECK constraint expression to string with literal values.

    SQLAlchemy's IN(...) with enum/list values uses POSTCOMPILE placeholders
    (e.g. __[POSTCOMPILE_param_1]); those must be expanded to literals for
    DDL execution. Use literal_binds=True to inline values.
    """
    if hasattr(sqltext, "compile"):
        from sqlalchemy.dialects import postgresql

        compiled = sqltext.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
        return str(compiled)
    return str(sqltext)


def _python_scalar_to_sql_literal(value: Any) -> str | None:
    """
    Map a Python scalar to a SQL DEFAULT fragment (dialect-agnostic literals).

    Used when SQLAlchemy's column ``default`` carries a Python value (e.g. SQLModel
    ``Field(default=date(...))``). Must not use ``str(value)`` alone: bare dates
    would emit ``1970-01-01``, which PostgreSQL parses as integer subtraction, not
    a DATE literal. See docs/technical/05-model-column-defaults.md.

    Traceability: docs/requirements/01-functional.md (Schema parity: column defaults).

    Returns:
        A string safe to place after ``DEFAULT `` in DDL, or None if no static
        literal can be produced (unknown types, non-finite float).
    """
    if isinstance(value, datetime):
        inner = value.isoformat(sep=" ").replace("'", "''")
        return f"'{inner}'"
    if isinstance(value, date):
        return f"'{value.isoformat()}'"
    if isinstance(value, time):
        return f"'{value.isoformat()}'"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, Enum):
        return _python_scalar_to_sql_literal(value.value)
    if isinstance(value, UUID):
        return "'" + str(value).replace("'", "''") + "'"
    return None


def _default_expr(column: Any, _dialect: Dialect | None) -> str | None:
    """
    Return a column default as a SQL expression string for DDL, or None.

    Prefer ``server_default``; otherwise use ``default`` (Python-side). Callable
    ``.arg`` (e.g. ``default_factory``) yields None—no static DDL.

    For ``.arg`` that is a SQLAlchemy :class:`~sqlalchemy.sql.elements.ClauseElement`
    (typical for ``server_default=text(...)`` and many reflected defaults),
    ``str(.arg)`` is used so quoting matches SQLAlchemy's rendering.

    For other ``.arg`` values, :func:`_python_scalar_to_sql_literal` produces quoted
    literals. See docs/technical/05-model-column-defaults.md (PostgreSQL date bug).

    Traceability: docs/requirements/01-functional.md (Schema parity: columns, defaults).
    """
    default = getattr(column, "server_default", None) or getattr(column, "default", None)
    if default is None:
        return None
    if hasattr(default, "arg") and default.arg is not None:
        if callable(default.arg):
            return None  # Python-side default; no DDL expression
        if isinstance(default.arg, ClauseElement):
            return str(default.arg)
        return _python_scalar_to_sql_literal(default.arg)
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
    is_single_pk = table.primary_key and len(table.primary_key.columns) == 1
    pk_col_name = list(table.primary_key.columns)[0].name if is_single_pk else None
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
        autoincrement = bool(is_single_pk and is_pk_col and is_integer and sa_auto)
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
                expression = _check_expression_str(constraint.sqltext)
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
        If schema_normalizer is provided (e.g. dbconform Dialect), its
        normalize_reflected_table is applied so model-side internal schema
        compares equal to database-side internal schema.
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
