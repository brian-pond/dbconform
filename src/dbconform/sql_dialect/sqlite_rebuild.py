"""
SQLite table-rebuild logic for adding constraints to existing tables.

SQLite does not support ALTER TABLE ADD CONSTRAINT for CHECK, UNIQUE, or FOREIGN KEY.
This module implements the workaround: create new table with target schema, copy data,
drop old, rename new. See docs/requirements/01-functional.md (Schema parity scope).
"""

from __future__ import annotations

from dataclasses import replace

from dbconform.internal.objects import CheckDef, QualifiedName, TableDef
from dbconform.sql_dialect.base import Dialect
from dbconform.sql_dialect.sqlite import SQLiteDialect


def _rewrite_check_expressions_for_new_table(
    check_constraints: tuple[CheckDef, ...],
    original_table_name: str,
) -> tuple[CheckDef, ...]:
    """
    Rewrite CHECK expressions so column references use unqualified names.

    Model-derived CHECKs often reference table.col (e.g. execution_lanes.concurrency_mode).
    When creating _dbconform_new, those refs are invalid; unqualified col names
    refer to the table being created. Strip the table qualifier.
    """
    rewritten: list[CheckDef] = []
    for ck in check_constraints:
        expr = ck.expression
        expr = expr.replace(f'"{original_table_name}".', "").replace(
            f"{original_table_name}.", ""
        )
        rewritten.append(CheckDef(name=ck.name, expression=expr))
    return tuple(rewritten)


def build_rebuild_statements(
    dialect: Dialect,
    table_name: QualifiedName,
    target_table: TableDef,
    old_table: TableDef,
) -> list[str]:
    """
    Produce SQL statements to rebuild a table with the target schema.

    Order: PRAGMA foreign_keys=OFF, CREATE _new, CREATE indexes on _new,
    INSERT INTO _new SELECT..., DROP old, RENAME _new TO old, PRAGMA foreign_keys=ON.

    Args:
        dialect: Must be SQLiteDialect (or compatible).
        table_name: Qualified name of the existing table.
        target_table: Desired schema (model-side).
        old_table: Current schema (DB-side); used for column mapping in INSERT.

    Returns:
        List of SQL statements to execute in order.
    """
    if not isinstance(dialect, SQLiteDialect):
        raise ValueError("Table rebuild is only supported for SQLite")
    sqlite_dialect: SQLiteDialect = dialect

    base_name = table_name.name
    new_name = f"{base_name}_dbconform_new"
    qualified_new = QualifiedName(schema=table_name.schema, name=new_name)
    rewritten_checks = _rewrite_check_expressions_for_new_table(
        target_table.check_constraints, base_name
    )
    new_table_def = replace(
        target_table,
        name=qualified_new,
        check_constraints=rewritten_checks,
    )

    statements: list[str] = []

    # Disable FK checks during rebuild (other tables may reference this one)
    statements.append("PRAGMA foreign_keys=OFF")

    # Create new table with target schema
    create_sql = sqlite_dialect.create_table_sql(new_table_def)
    statements.append(create_sql)

    # Create indexes on new table
    for idx in target_table.indexes:
        idx_sql = sqlite_dialect.create_index_sql(idx, qualified_new)
        statements.append(idx_sql)

    # Copy data: map columns from old to new; new columns get default or NULL
    old_cols = {c.name: c for c in old_table.columns}
    insert_cols: list[str] = []
    select_parts: list[str] = []
    quote = sqlite_dialect._quote
    for col in target_table.columns:
        insert_cols.append(quote(col.name))
        if col.name in old_cols:
            select_parts.append(quote(col.name))
        else:
            # New column not in old table - use default or NULL
            if col.default is not None:
                select_parts.append(sqlite_dialect.default_for_ddl(col.default))
            else:
                select_parts.append("NULL")

    tbl_old = sqlite_dialect.qualified_table(table_name)
    tbl_new = sqlite_dialect.qualified_table(qualified_new)
    insert_sql = (
        f"INSERT INTO {tbl_new} ({', '.join(insert_cols)}) "
        f"SELECT {', '.join(select_parts)} FROM {tbl_old}"
    )
    statements.append(insert_sql)

    # Drop old table
    statements.append(f"DROP TABLE {tbl_old}")

    # Rename new to original name
    statements.append(f"ALTER TABLE {tbl_new} RENAME TO {quote(base_name)}")

    # Restore FK checks
    statements.append("PRAGMA foreign_keys=ON")

    return statements
