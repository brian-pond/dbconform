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

from sqlalchemy import Column, Table
from sqlalchemy.engine import Dialect
from sqlalchemy.schema import (
    CheckConstraint,
    ForeignKeyConstraint,
    Identity,
    UniqueConstraint,
)
from sqlalchemy.schema import (
    Sequence as SaSequence,
)
from sqlalchemy.sql.elements import ClauseElement, TextClause, UnaryExpression
from sqlalchemy.sql.operators import asc_op, desc_op

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


def _ingest_model_column_type(
    column: Any,
    *,
    model_type_dialect: Dialect | None = None,
) -> str:
    """
    Resolve a model column type to a neutral data_type_name (ingestion path).

    Uses name-based mapping in :func:`sa_column_to_neutral_type`, not SQLAlchemy
    compile. ``model_type_dialect`` is passed through for ``TypeDecorator``
    resolution only (GitHub #10).
    """
    return sa_column_to_neutral_type(column, model_type_dialect=model_type_dialect)


def _reflect_column_type(column: Any, reflection_dialect: Dialect) -> str:
    """
    Resolve a reflected column type by compiling with the connection dialect.

    Reflection path only. Output is normalized to neutral form by the backend
    Dialect's ``normalize_reflected_table`` / ``to_neutral_type``.
    """
    return column.type.compile(dialect=reflection_dialect)


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


def _default_expr(column: Any, _reflection_dialect: Dialect | None) -> str | None:
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


def _has_real_default_generator(column: Any) -> bool:
    """
    Return True when the column has a default generator that blocks implicit autoincrement.

    SQLAlchemy treats server defaults, Identity, Sequence, and non-empty Python-side defaults
    as generators. Empty ``ColumnDefault(None)`` placeholders (common on SQLModel PK fields
    with ``Field(default=None)``) are ignored. See GitHub #2.
    """
    server_default = getattr(column, "server_default", None)
    if server_default is not None:
        return True

    default = getattr(column, "default", None)
    if default is None:
        return False
    if isinstance(default, SaSequence):
        return True

    if hasattr(default, "arg"):
        arg = default.arg
        if isinstance(arg, SaSequence):
            return True
        if callable(arg):
            return True
        if isinstance(arg, ClauseElement):
            return True
        return arg is not None

    return hasattr(default, "text") and default.text is not None


def _index_expression_to_str(expr: Any) -> tuple[str, str | None]:
    """
    Convert one SQLAlchemy index expression to a DDL fragment and optional column name.

    Returns (ddl_fragment, column_name). column_name is None for ``text()`` expressions.
    """
    if isinstance(expr, str):
        return expr, expr
    if isinstance(expr, Column):
        return expr.name, expr.name
    if isinstance(expr, TextClause):
        return str(expr), None
    if isinstance(expr, UnaryExpression):
        inner = expr.element
        if isinstance(inner, Column):
            col_name = inner.name
            if expr.modifier is desc_op:
                return f"{col_name} DESC", col_name
            if expr.modifier is asc_op:
                return f"{col_name} ASC", col_name
        return str(expr), None
    if hasattr(expr, "name"):
        name = expr.name
        return name, name
    return str(expr), None


def _index_where_clause(idx: Any) -> str | None:
    """Extract partial-index WHERE predicate from a SQLAlchemy Index."""
    where = idx.dialect_kwargs.get("postgresql_where")
    if where is None:
        where = idx.dialect_kwargs.get("sqlite_where")
    if where is None:
        return None
    return str(where)


def _index_to_def(idx: Any, table: Table) -> IndexDef:
    """
    Build IndexDef from a SQLAlchemy Index, preserving sort order and partial predicates.

    See docs/requirements/01-functional.md (Schema parity scope — indexes); GitHub #6.
    """
    column_exprs: list[str] = []
    column_names: list[str] = []
    for expr in idx.expressions:
        ddl_frag, col_name = _index_expression_to_str(expr)
        column_exprs.append(ddl_frag)
        if col_name is not None:
            column_names.append(col_name)

    return IndexDef(
        name=idx.name or f"ix_{table.name}_{'_'.join(column_names)}",
        column_names=tuple(column_names),
        unique=idx.unique or False,
        column_exprs=tuple(column_exprs),
        where=_index_where_clause(idx),
    )


def _column_is_implicit_autoincrement_pk(
    column: Any,
    *,
    is_single_pk: bool,
    pk_col_name: str | None,
    integer_type_names: tuple[str, ...],
) -> bool:
    """
    Decide whether a column should be treated as autoincrement in internal schema.

    Policy: dbconform prefers explicit SQLAlchemy/SQLModel model declarations, but we
    intentionally support SQLAlchemy's documented implicit autoincrement behavior for
    compatibility (single integer PK with ``autoincrement='auto'`` and no other default
    generator). See docs/requirements/01-functional.md (Schema parity scope).
    """
    is_pk_col = pk_col_name is not None and column.name == pk_col_name
    is_integer = type(column.type).__name__ in integer_type_names
    if not (is_single_pk and is_pk_col and is_integer):
        return False

    identity = getattr(column, "identity", None)
    if isinstance(identity, Identity):
        return True

    sa_auto = getattr(column, "autoincrement", False)
    if sa_auto is True:
        return True
    if sa_auto is False:
        return False
    if isinstance(sa_auto, str):
        if sa_auto != "auto":
            return False
        # SQLAlchemy docs: implicit autoincrement applies only when no other
        # default-generating construct is present.
        return not _has_real_default_generator(column)
    return False


def _extract_table_def(
    table: Table,
    target_schema: str | None,
    *,
    reflection_dialect: Dialect | None = None,
    model_type_dialect: Dialect | None = None,
) -> TableDef:
    """
    Build a TableDef from a SQLAlchemy Table.

    Column types use one of two resolution strategies (mutually exclusive):

    - **Reflection** (``reflection_dialect`` set): compile each column type with
      the connection dialect; caller applies ``normalize_reflected_table``.
    - **Model ingestion** (``reflection_dialect`` is None): map types to neutral
      names via :func:`_ingest_model_column_type`; optional ``model_type_dialect``
      resolves ``TypeDecorator`` for the conform target backend.

    See docs/technical/02-architecture.md (Types).
    """
    schema = table.schema if table.schema is not None else target_schema
    qualified_name = QualifiedName(schema=schema, name=table.name)

    columns: list[ColumnDef] = []
    # Only the single integer PK column should have autoincrement=True (SA uses "auto" on others too).
    is_single_pk = table.primary_key and len(table.primary_key.columns) == 1
    pk_col_name = list(table.primary_key.columns)[0].name if is_single_pk else None
    _integer_type_names = ("Integer", "INTEGER", "BigInteger", "BIGINT", "SmallInteger", "SMALLINT")
    for col in table.c:
        default = _default_expr(col, reflection_dialect)
        if reflection_dialect is not None:
            type_str = _reflect_column_type(col, reflection_dialect)
        else:
            type_str = _ingest_model_column_type(col, model_type_dialect=model_type_dialect)
        comment = getattr(col, "comment", None)
        autoincrement = _column_is_implicit_autoincrement_pk(
            col,
            is_single_pk=bool(is_single_pk),
            pk_col_name=pk_col_name,
            integer_type_names=_integer_type_names,
        )
        col_info = getattr(col, "info", None) or {}
        backfill_column = col_info.get("dbconform_backfill")
        backfill_sql = col_info.get("dbconform_backfill_sql")
        if backfill_column is not None:
            backfill_column = str(backfill_column).strip() or None
        if backfill_sql is not None:
            backfill_sql = str(backfill_sql).strip() or None
        columns.append(
            ColumnDef(
                name=col.name,
                data_type_name=type_str,
                nullable=col.nullable,
                default=default,
                comment=comment,
                autoincrement=autoincrement,
                backfill_column=backfill_column,
                backfill_sql=backfill_sql,
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
        indexes.append(_index_to_def(idx, table))

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
        model_type_dialect: Dialect | None = None,
        schema_normalizer: _SchemaNormalizer | None = None,
    ) -> ModelSchema:
        """
        Build ModelSchema from one or more model classes.

        Each model must have __table__ (SQLAlchemy Table). Column types use the
        model ingestion path (:func:`_ingest_model_column_type`). When
        ``model_type_dialect`` is the conform target connection dialect,
        ``TypeDecorator`` columns resolve via ``load_dialect_impl`` (GitHub #10).
        ``target_schema`` is used when table.schema is None (e.g. PostgreSQL
        default schema). If ``schema_normalizer`` is provided (e.g. dbconform
        Dialect), its ``normalize_reflected_table`` is applied so model-side
        internal schema compares equal to database-side internal schema.
        """
        if isinstance(models, type):
            model_seq: Sequence[type] = (models,)
        else:
            model_seq = models
        instance = cls()
        for model in model_seq:
            table = _get_table_from_model(model)
            table_def = _extract_table_def(
                table,
                target_schema,
                model_type_dialect=model_type_dialect,
            )
            if schema_normalizer is not None:
                table_def = schema_normalizer.normalize_reflected_table(table_def)
            instance._tables[table_def.name] = table_def
        return instance
