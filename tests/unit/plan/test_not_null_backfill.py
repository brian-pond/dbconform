"""Unit tests for NOT NULL column backfill planning (GitHub #12 Gap 1)."""

from dbconform.internal.objects import ColumnDef, QualifiedName, TableDef
from dbconform.plan.not_null_backfill import (
    build_add_not_null_column_sql,
    resolve_not_null_backfill_expression,
    sentinel_backfill_expression,
)
from dbconform.sql_dialect.postgresql import PostgreSQLDialect


def test_resolve_backfill_from_column_info() -> None:
    """``dbconform_backfill`` maps to a quoted peer column name."""
    dialect = PostgreSQLDialect()
    table = TableDef(
        name=QualifiedName("broker", "broker_bucket"),
        columns=(
            ColumnDef("bucket_key", "VARCHAR(255)", nullable=False),
            ColumnDef("created_at", "TIMESTAMPTZ", nullable=False),
        ),
    )
    col = ColumnDef(
        "updated_at",
        "TIMESTAMPTZ",
        nullable=False,
        backfill_column="created_at",
    )
    expr = resolve_not_null_backfill_expression(
        col,
        table,
        backfill_sentinel_timestamps=False,
        dialect=dialect,
    )
    assert expr == '"created_at"'


def test_resolve_backfill_sentinel_opt_in() -> None:
    """Sentinel timestamps require explicit opt-in."""
    dialect = PostgreSQLDialect()
    table = TableDef(name=QualifiedName("public", "t"))
    col = ColumnDef("updated_at", "TIMESTAMPTZ", nullable=False)
    assert (
        resolve_not_null_backfill_expression(
            col,
            table,
            backfill_sentinel_timestamps=False,
            dialect=dialect,
        )
        is None
    )
    assert (
        resolve_not_null_backfill_expression(
            col,
            table,
            backfill_sentinel_timestamps=True,
            dialect=dialect,
        )
        == sentinel_backfill_expression("TIMESTAMPTZ")
    )


def test_postgresql_multi_step_add_not_null_on_nonempty_table() -> None:
    """Non-empty table + backfill emits ADD NULL → UPDATE → SET NOT NULL."""
    dialect = PostgreSQLDialect()
    table_name = QualifiedName("broker", "broker_bucket")
    table = TableDef(
        name=table_name,
        columns=(
            ColumnDef("created_at", "TIMESTAMPTZ", nullable=False),
            ColumnDef("updated_at", "TIMESTAMPTZ", nullable=False, backfill_column="created_at"),
        ),
    )
    new_col = ColumnDef(
        "updated_at",
        "TIMESTAMPTZ",
        nullable=False,
        backfill_column="created_at",
    )
    sql, skip = build_add_not_null_column_sql(
        dialect,
        table_name,
        new_col,
        table,
        table_has_rows=True,
        allow_not_null_backfill=True,
        backfill_sentinel_timestamps=False,
    )
    assert skip is None
    assert sql is not None
    assert "ADD COLUMN" in sql
    assert "UPDATE" in sql
    assert "SET NOT NULL" in sql
    assert '"created_at"' in sql


def test_add_not_null_blocked_without_opt_in() -> None:
    """Non-empty table without allow_not_null_backfill yields skip reason."""
    dialect = PostgreSQLDialect()
    table_name = QualifiedName("broker", "broker_bucket")
    table = TableDef(
        name=table_name,
        columns=(ColumnDef("updated_at", "TIMESTAMPTZ", nullable=False),),
    )
    col = ColumnDef("updated_at", "TIMESTAMPTZ", nullable=False, backfill_column="created_at")
    sql, skip = build_add_not_null_column_sql(
        dialect,
        table_name,
        col,
        table,
        table_has_rows=True,
        allow_not_null_backfill=False,
        backfill_sentinel_timestamps=False,
    )
    assert sql is None
    assert skip is not None
    assert "allow_not_null_backfill=False" in skip
