"""
Unit tests for PostgreSQLDialect DDL output.

Traceability: docs/requirements/01-functional.md (Schema parity, Identifiers and quoting).
"""

from dbconform.schema.objects import (
    ColumnDef,
    PrimaryKeyDef,
    QualifiedName,
    TableDef,
    UniqueDef,
)
from dbconform.sql_dialect.postgresql import PostgreSQLDialect


def test_postgresql_quote_identifier() -> None:
    """PostgreSQL uses double-quoted identifiers."""
    dialect = PostgreSQLDialect()
    assert dialect._quote("foo") == '"foo"'
    assert dialect.qualified_table(QualifiedName(None, "t")) == '"t"'
    assert dialect.qualified_table(QualifiedName("public", "t")) == '"public"."t"'


def test_postgresql_create_table_serial_pk() -> None:
    """Single autoincrement PK column becomes SERIAL PRIMARY KEY."""
    dialect = PostgreSQLDialect()
    table = TableDef(
        name=QualifiedName("public", "foo"),
        columns=(
            ColumnDef("id", "INTEGER", nullable=False, autoincrement=True),
            ColumnDef("name", "VARCHAR(255)", nullable=False),
        ),
        primary_key=PrimaryKeyDef(("id",)),
    )
    sql = dialect.create_table_sql(table)
    assert "SERIAL" in sql
    assert "PRIMARY KEY" in sql
    assert '"public"."foo"' in sql
    assert "VARCHAR(255)" in sql


def test_postgresql_alter_column_sql() -> None:
    """PostgreSQL emits ALTER COLUMN for type and nullability."""
    dialect = PostgreSQLDialect()
    tbl = QualifiedName("public", "t")
    old_col = ColumnDef("x", "INTEGER", nullable=True)
    new_col = ColumnDef("x", "BIGINT", nullable=False)
    sql = dialect.alter_column_sql(tbl, old_col, new_col)
    assert sql is not None
    assert "ALTER COLUMN" in sql
    assert "TYPE BIGINT" in sql
    assert "SET NOT NULL" in sql


def test_postgresql_drop_index_schema_qualified() -> None:
    """PostgreSQL DROP INDEX can be schema-qualified."""
    dialect = PostgreSQLDialect()
    sql = dialect.drop_index_sql("idx_foo", QualifiedName("public", "t"))
    assert "DROP INDEX" in sql
    assert '"public"."idx_foo"' in sql


def test_postgresql_drop_unique_sql() -> None:
    """PostgreSQL supports DROP CONSTRAINT for unique."""
    dialect = PostgreSQLDialect()
    tbl = QualifiedName(None, "t")
    u = UniqueDef("uq_name", ("col",))
    sql = dialect.drop_unique_sql(tbl, u)
    assert sql is not None
    assert "DROP CONSTRAINT" in sql
    assert '"uq_name"' in sql


def test_postgresql_would_shrink() -> None:
    """PostgreSQL dialect would_shrink for VARCHAR length."""
    dialect = PostgreSQLDialect()
    old_500 = ColumnDef("name", "VARCHAR(500)", nullable=False)
    new_255 = ColumnDef("name", "VARCHAR(255)", nullable=False)
    assert dialect.would_shrink(old_500, new_255) is True
    assert dialect.would_shrink(new_255, old_500) is False


def test_postgresql_parse_varchar_length() -> None:
    """Base _parse_varchar_length parses VARCHAR(n) and CHARACTER VARYING(n)."""
    dialect = PostgreSQLDialect()
    assert dialect._parse_varchar_length("VARCHAR(255)") == 255
    assert dialect._parse_varchar_length("CHARACTER VARYING(100)") == 100
    assert dialect._parse_varchar_length("CHAR(10)") == 10
    assert dialect._parse_varchar_length("INTEGER") is None
    assert dialect._parse_varchar_length("VARCHAR( 500 )") == 500


def test_postgresql_to_neutral_type() -> None:
    """PostgreSQL to_neutral_type normalizes reflected type strings."""
    dialect = PostgreSQLDialect()
    assert dialect.to_neutral_type("DOUBLE PRECISION") == "FLOAT"
    assert dialect.to_neutral_type("REAL") == "FLOAT"
    assert dialect.to_neutral_type("CHARACTER VARYING(255)") == "VARCHAR(255)"
    assert dialect.to_neutral_type("varchar(100)") == "VARCHAR(100)"
    assert dialect.to_neutral_type("INTEGER") == "INTEGER"
    assert dialect.to_neutral_type("VARCHAR  ( 50 )") == "VARCHAR(50)"


def test_postgresql_to_ddl_type_serial() -> None:
    """PostgreSQL to_ddl_type returns SERIAL/BIGSERIAL for autoincrement PK."""
    dialect = PostgreSQLDialect()
    col_int = ColumnDef("id", "INTEGER", nullable=False, autoincrement=True)
    col_big = ColumnDef("id", "BIGINT", nullable=False, autoincrement=True)
    assert dialect.to_ddl_type(col_int, pk_autoincrement=True) == "SERIAL"
    assert dialect.to_ddl_type(col_big, pk_autoincrement=True) == "BIGSERIAL"
    assert dialect.to_ddl_type(col_int, pk_autoincrement=False) == "INTEGER"
    assert dialect.to_ddl_type(col_int, pk_autoincrement=True) == "SERIAL"


def test_postgresql_to_ddl_type_plain() -> None:
    """PostgreSQL to_ddl_type returns data_type_name when not SERIAL."""
    dialect = PostgreSQLDialect()
    col = ColumnDef("name", "VARCHAR(255)", nullable=False)
    assert dialect.to_ddl_type(col) == "VARCHAR(255)"
    assert dialect.to_ddl_type(col, pk_autoincrement=False) == "VARCHAR(255)"


def test_postgresql_normalize_reflected_table_normalizes_bool_default_case() -> None:
    """Reflected bool default case should normalize to model-side literal format."""
    dialect = PostgreSQLDialect()
    table = TableDef(
        name=QualifiedName("public", "bom"),
        columns=(ColumnDef("lot_tracking", "BOOLEAN", nullable=False, default="false"),),
    )
    normalized = dialect.normalize_reflected_table(table)
    assert normalized.columns[0].default == "FALSE"
