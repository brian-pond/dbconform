"""Unit tests for CHECK expression DDL helpers (GitHub #12 Gaps 2–3)."""

from dbconform.sql_dialect.base import Dialect
from dbconform.sql_dialect.check_expression import (
    format_check_expression_for_ddl,
    is_wrapped_in_parens,
    normalize_check_expression_text,
    strip_outer_parens,
)
from dbconform.schema.objects import CheckDef, ColumnDef, QualifiedName, TableDef
from dbconform.sql_dialect.postgresql import PostgreSQLDialect


class _MinimalDialect(Dialect):
    """Concrete dialect stub for base CHECK DDL tests."""

    @property
    def name(self) -> str:
        return "minimal"

    def _quote(self, name: str) -> str:
        return f'"{name}"'

    def create_table_sql(self, table):  # noqa: ANN001, ARG002
        raise NotImplementedError

    def add_column_sql(self, table_name, column):  # noqa: ANN001, ARG002
        raise NotImplementedError


def test_is_wrapped_in_parens_or_expression_not_fully_wrapped() -> None:
    """``(A) OR (B)`` is not one outer wrapper; ``((A) OR (B))`` is."""
    assert is_wrapped_in_parens("(A) OR (B)") is False
    assert is_wrapped_in_parens("((A) OR (B))") is True


def test_strip_outer_parens_does_not_corrupt_or_expression() -> None:
    """Naive stripping would break OR branches; safe strip preserves meaning."""
    expr = "(destination = 'general' AND bucket_id IS NULL) OR (destination = 'bucket' AND bucket_id IS NOT NULL)"
    assert strip_outer_parens(expr) == expr
    assert normalize_check_expression_text(f"({expr})") == expr


def test_format_check_expression_for_ddl_wraps_or_expression() -> None:
    """Top-level OR must be inside CHECK parentheses."""
    expr = "(dispatch_role = 'general' AND bucket_id IS NULL) OR (dispatch_role = 'bucket' AND bucket_id IS NOT NULL)"
    body = format_check_expression_for_ddl(expr)
    assert body.startswith("(")
    assert " OR " in body


def test_format_check_expression_for_ddl_wraps_boolean_equality() -> None:
    """Boolean equality between parenthesized subexpressions must stay inside CHECK."""
    expr = "(dispatch_role = 'system') = (NOT is_assignable)"
    body = format_check_expression_for_ddl(expr)
    assert body == f"({expr})"


def test_add_check_sql_emits_valid_postgresql_or_check() -> None:
    """ADD CHECK DDL keeps OR inside the predicate (GitHub #12 Gap 2)."""
    dialect = _MinimalDialect()
    ck = CheckDef(
        name="broker_message_destination_bucket_ck",
        expression=(
            "(destination = 'general' AND bucket_id IS NULL) OR "
            "(destination = 'bucket' AND bucket_id IS NOT NULL)"
        ),
    )
    sql = dialect.add_check_sql(QualifiedName("broker", "broker_message"), ck)
    assert "CHECK (" in sql
    assert sql.index("CHECK (") < sql.index(" OR ")
    assert sql.rstrip().endswith(")")


def test_postgresql_normalize_preserves_or_check_after_whitespace() -> None:
    """Normalization must not strip OR branches (GitHub #12 Gap 4)."""
    dialect = PostgreSQLDialect()
    table = TableDef(name=QualifiedName("broker", "broker_message"))
    expr = (
        "(destination = 'general' AND bucket_id IS NULL) OR "
        "(destination = 'bucket' AND bucket_id IS NOT NULL)"
    )
    normalized = dialect._normalize_check_expression(expr, table_def=table)
    assert " OR " in normalized
    assert normalized.startswith("(destination")


def test_sqlite_normalize_reflected_table_strips_in_check_outer_parens() -> None:
    """Reflected ``(col IN (...))`` compares equal to model ``col IN (...)`` (GitHub #12)."""
    from dbconform.sql_dialect.sqlite import SQLiteDialect

    dialect = SQLiteDialect()
    table = TableDef(
        name=QualifiedName(None, "items"),
        columns=(ColumnDef("level", "VARCHAR(50)", nullable=False),),
        check_constraints=(
            CheckDef(
                name="ck_level",
                expression="(level IN ('info', 'warning', 'error'))",
            ),
        ),
    )
    normalized = dialect.normalize_reflected_table(table)
    assert normalized.check_constraints[0].expression == "level IN ('info', 'warning', 'error')"
