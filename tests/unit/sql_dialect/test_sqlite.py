"""
Unit tests for SQLiteDialect DDL output.

Traceability: docs/requirements/01-functional.md (Schema parity).
"""

from dbconform.schema.objects import (
    ColumnDef,
    QualifiedName,
    TableDef,
)
from dbconform.sql_dialect.sqlite import SQLiteDialect


def test_sqlite_default_for_ddl_now_becomes_current_timestamp() -> None:
    """PostgreSQL now() is translated to CURRENT_TIMESTAMP for SQLite compatibility."""
    dialect = SQLiteDialect()
    assert dialect.default_for_ddl("now()") == "CURRENT_TIMESTAMP"
    assert dialect.default_for_ddl("NOW()") == "CURRENT_TIMESTAMP"
    assert dialect.default_for_ddl("  now()  ") == "CURRENT_TIMESTAMP"


def test_sqlite_default_for_ddl_localtimestamp_becomes_current_timestamp() -> None:
    """PostgreSQL localtimestamp is translated to CURRENT_TIMESTAMP."""
    dialect = SQLiteDialect()
    assert dialect.default_for_ddl("localtimestamp") == "CURRENT_TIMESTAMP"
    assert dialect.default_for_ddl("localtimestamp()") == "CURRENT_TIMESTAMP"


def test_sqlite_default_for_ddl_current_timestamp_preserved() -> None:
    """CURRENT_TIMESTAMP is valid in SQLite and preserved (uppercased)."""
    dialect = SQLiteDialect()
    assert dialect.default_for_ddl("current_timestamp") == "CURRENT_TIMESTAMP"
    assert dialect.default_for_ddl("CURRENT_TIMESTAMP") == "CURRENT_TIMESTAMP"


def test_sqlite_create_table_with_now_default_emits_current_timestamp() -> None:
    """CREATE TABLE with now() default emits CURRENT_TIMESTAMP (SQLite-compatible)."""
    dialect = SQLiteDialect()
    table = TableDef(
        name=QualifiedName(None, "audit_logs"),
        columns=(
            ColumnDef("id", "INTEGER", nullable=False),
            ColumnDef(
                "occurred_at",
                "TIMESTAMP",
                nullable=False,
                default="now()",
            ),
        ),
    )
    sql = dialect.create_table_sql(table)
    assert "DEFAULT CURRENT_TIMESTAMP" in sql
    assert "now()" not in sql
