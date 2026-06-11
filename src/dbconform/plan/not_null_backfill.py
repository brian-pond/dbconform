"""
Multi-step ADD COLUMN NOT NULL plans for non-empty tables (GitHub #12 Gap 1).

Backfill sources are stateless: column ``info`` hints, ``server_default``, or opt-in
sentinel timestamps — never product-specific peer-column heuristics.
"""

from __future__ import annotations

import re

from dbconform.compare.diff import DiffResult
from dbconform.internal.objects import ColumnDef, QualifiedName, TableDef
from dbconform.sql_dialect.base import Dialect

_TEMPORAL_TYPES = frozenset(
    {
        "TIMESTAMPTZ",
        "TIMESTAMP",
        "TIMESTAMP WITH TIME ZONE",
        "TIMESTAMP WITHOUT TIME ZONE",
        "DATE",
    }
)

_SENTINEL_TIMESTAMPTZ = "'1900-01-01T00:00:00+00'::timestamptz"
_SENTINEL_TIMESTAMP = "'1900-01-01 00:00:00'::timestamp"
_SENTINEL_DATE = "'1900-01-01'::date"


def tables_needing_row_probe(diff: DiffResult) -> list[QualifiedName]:
    """Return modified tables that add at least one NOT NULL column."""
    names: list[QualifiedName] = []
    for name, table_diff in diff.modified_tables.items():
        if any(not col.nullable for col in table_diff.added_columns):
            names.append(name)
    return names


def is_temporal_type(data_type_name: str) -> bool:
    """Return True when the neutral/DDL type is a date or timestamp."""
    upper = " ".join(data_type_name.split()).strip().upper()
    if upper in _TEMPORAL_TYPES:
        return True
    return upper.startswith("TIMESTAMP") or upper == "DATE"


def sentinel_backfill_expression(data_type_name: str) -> str | None:
    """Return opt-in sentinel SQL for temporal types, or None."""
    upper = " ".join(data_type_name.split()).strip().upper()
    if upper in ("TIMESTAMPTZ", "TIMESTAMP WITH TIME ZONE"):
        return _SENTINEL_TIMESTAMPTZ
    if upper in ("TIMESTAMP", "TIMESTAMP WITHOUT TIME ZONE"):
        return _SENTINEL_TIMESTAMP
    if upper == "DATE":
        return _SENTINEL_DATE
    if upper.startswith("TIMESTAMP"):
        return _SENTINEL_TIMESTAMP
    return None


def resolve_not_null_backfill_expression(
    column: ColumnDef,
    table_def: TableDef,
    *,
    backfill_sentinel_timestamps: bool,
    dialect: Dialect,
) -> str | None:
    """
    Resolve the SQL expression used to backfill a new NOT NULL column on existing rows.

    Priority: ``backfill_sql`` → ``backfill_column`` (same table) → ``default`` →
    opt-in sentinel for temporal types.
    """
    if column.backfill_sql:
        return column.backfill_sql.strip()
    if column.backfill_column:
        peer = column.backfill_column.strip()
        if peer not in table_def.column_by_name():
            return None
        return dialect.quote_identifier(peer)
    if column.default is not None:
        expr = column.default.strip()
        if dialect.name == "sqlite":
            expr = dialect.default_for_ddl(expr)
        return expr
    if backfill_sentinel_timestamps and is_temporal_type(column.data_type_name):
        return sentinel_backfill_expression(column.data_type_name)
    return None


def backfill_is_literal_expression(expression: str) -> bool:
    """
    Return True when backfill is a constant/default literal (not a column reference).

    Used for SQLite ADD COLUMN NOT NULL DEFAULT on non-empty tables.
    """
    expr = expression.strip()
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", expr):
        return False
    return True


def build_add_not_null_column_sql(
    dialect: Dialect,
    table_name: QualifiedName,
    column: ColumnDef,
    table_def: TableDef,
    *,
    table_has_rows: bool,
    allow_not_null_backfill: bool,
    backfill_sentinel_timestamps: bool,
) -> tuple[str | None, str | None]:
    """
    Build SQL to add a NOT NULL column, optionally multi-step when rows exist.

    Returns ``(sql, skip_reason)`` — exactly one of the two is non-None.
    """
    if not column.nullable and not table_has_rows:
        return dialect.add_column_sql(table_name, column), None

    if column.nullable:
        return dialect.add_column_sql(table_name, column), None

    if not table_has_rows:
        return dialect.add_column_sql(table_name, column), None

    if not allow_not_null_backfill:
        return None, (
            f"Add NOT NULL column `{column.name}` blocked: table has rows and "
            "allow_not_null_backfill=False. Run manual backfill SQL or enable "
            "allow_not_null_backfill on apply_changes()."
        )

    backfill = resolve_not_null_backfill_expression(
        column,
        table_def,
        backfill_sentinel_timestamps=backfill_sentinel_timestamps,
        dialect=dialect,
    )
    if backfill is None:
        return None, (
            f"Add NOT NULL column `{column.name}` blocked: no backfill strategy. "
            "Set Column.info dbconform_backfill / dbconform_backfill_sql, "
            "provide server_default, or enable backfill_sentinel_timestamps."
        )

    if dialect.name == "postgresql":
        return _postgresql_add_not_null_steps(dialect, table_name, column, backfill), None

    if dialect.name == "sqlite" and backfill_is_literal_expression(backfill):
        return _sqlite_add_not_null_with_default(dialect, table_name, column, backfill), None

    tbl = dialect.qualified_table(table_name)
    col_q = dialect.quote_identifier(column.name)
    pg_type = dialect.to_ddl_type(column)
    stmts = [
        f"ALTER TABLE {tbl} ADD COLUMN {col_q} {pg_type}",
        f"UPDATE {tbl} SET {col_q} = {backfill} WHERE {col_q} IS NULL",
    ]
    return (
        None,
        (
            f"Add NOT NULL column `{column.name}` on SQLite blocked: backfill references "
            f"another column and SQLite cannot SET NOT NULL after ADD. Steps that would run: "
            + "; ".join(stmts)
        ),
    )


def _postgresql_add_not_null_steps(
    dialect: Dialect,
    table_name: QualifiedName,
    column: ColumnDef,
    backfill: str,
) -> str:
    """Emit nullable add → UPDATE → SET NOT NULL for PostgreSQL."""
    tbl = dialect.qualified_table(table_name)
    col_q = dialect.quote_identifier(column.name)
    pg_type = dialect.to_ddl_type(column)
    stmts = [
        f"ALTER TABLE {tbl} ADD COLUMN {col_q} {pg_type}",
        f"UPDATE {tbl} SET {col_q} = {backfill} WHERE {col_q} IS NULL",
        f"ALTER TABLE {tbl} ALTER COLUMN {col_q} SET NOT NULL",
    ]
    if column.default is not None:
        stmts.append(f"ALTER TABLE {tbl} ALTER COLUMN {col_q} SET DEFAULT {column.default}")
    return "; ".join(stmts)


def _sqlite_add_not_null_with_default(
    dialect: Dialect,
    table_name: QualifiedName,
    column: ColumnDef,
    backfill: str,
) -> str:
    """SQLite: NOT NULL + DEFAULT backfills existing rows in one ADD COLUMN."""
    tbl = dialect.qualified_table(table_name)
    col_q = dialect.quote_identifier(column.name)
    ddl_type = dialect.to_ddl_type(column)
    default_expr = dialect.default_for_ddl(backfill)
    return (
        f"ALTER TABLE {tbl} ADD COLUMN {col_q} {ddl_type} NOT NULL DEFAULT {default_expr}"
    )
