"""
PostgreSQL dialect: double-quoted identifiers, full ALTER support.

PostgreSQL supports ALTER COLUMN (type, nullability, default), ADD/DROP CONSTRAINT,
and schema-qualified objects. See docs/requirements/01-functional.md (Schema parity scope).
"""

from __future__ import annotations

import re

from modelsync.dialect.base import Dialect
from modelsync.schema.objects import (
    CheckDef,
    ColumnDef,
    ForeignKeyDef,
    IndexDef,
    QualifiedName,
    TableDef,
    UniqueDef,
)


def _length_from_type_expr(type_expr: str) -> int | None:
    """Parse VARCHAR(n) or CHAR(n) from type_expr; return n or None."""
    m = re.match(r"VARCHAR\s*\(\s*(\d+)\s*\)", type_expr, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.match(r"CHARACTER\s+VARYING\s*\(\s*(\d+)\s*\)", type_expr, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.match(r"CHAR\s*\(\s*(\d+)\s*\)", type_expr, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _pg_type_for_column(column: ColumnDef, pk_autoincrement: bool) -> str:
    """
    Return PostgreSQL type for a column (SERIAL/BIGSERIAL for autoincrement PK).
    """
    if pk_autoincrement and column.autoincrement:
        type_upper = column.type_expr.strip().upper()
        if type_upper in ("BIGINT", "INT8"):
            return "BIGSERIAL"
        return "SERIAL"
    return column.type_expr


class PostgreSQLDialect(Dialect):
    """DDL generation for PostgreSQL."""

    @property
    def name(self) -> str:
        return "postgresql"

    def _quote(self, name: str) -> str:
        return f'"{name}"'

    def create_table_sql(self, table: TableDef) -> str:
        """Generate CREATE TABLE with columns and table-level constraints."""
        parts: list[str] = []
        pk_inline = (
            table.primary_key
            and len(table.primary_key.column_names) == 1
            and any(
                c.autoincrement and c.name in table.primary_key.column_names
                for c in table.columns
            )
        )
        for col in table.columns:
            pg_type = _pg_type_for_column(
                col, pk_autoincrement=bool(pk_inline and table.primary_key)
            )
            seg = f"{self._quote(col.name)} {pg_type}"
            if pg_type not in ("SERIAL", "BIGSERIAL") and not col.nullable:
                seg += " NOT NULL"
            if pg_type not in ("SERIAL", "BIGSERIAL") and col.default is not None:
                seg += f" DEFAULT {col.default}"
            if pk_inline and table.primary_key and col.name in table.primary_key.column_names:
                seg += " PRIMARY KEY"
            parts.append(seg)
        if table.primary_key and not pk_inline:
            pk_cols = ", ".join(self._quote(c) for c in table.primary_key.column_names)
            parts.append(f"PRIMARY KEY ({pk_cols})")
        for u in table.unique_constraints:
            cols = ", ".join(self._quote(c) for c in u.column_names)
            name_part = f"CONSTRAINT {self._quote(u.name)} " if u.name else ""
            parts.append(f"{name_part}UNIQUE ({cols})")
        for fk in table.foreign_keys:
            cols = ", ".join(self._quote(c) for c in fk.column_names)
            ref_cols = ", ".join(self._quote(c) for c in fk.ref_column_names)
            ref = self.qualified_table(fk.ref_table)
            name_part = f"CONSTRAINT {self._quote(fk.name)} " if fk.name else ""
            parts.append(f"{name_part}FOREIGN KEY ({cols}) REFERENCES {ref} ({ref_cols})")
        for ck in table.check_constraints:
            name_part = f"CONSTRAINT {self._quote(ck.name)} " if ck.name else ""
            parts.append(f"{name_part}CHECK ({ck.expression})")
        body = ", ".join(parts)
        tbl = self.qualified_table(table.name)
        return f"CREATE TABLE {tbl} ({body})"

    def add_column_sql(self, table_name: QualifiedName, column: ColumnDef) -> str:
        """PostgreSQL supports ALTER TABLE ... ADD COLUMN."""
        seg = f"{self._quote(column.name)} {column.type_expr}"
        if not column.nullable:
            seg += " NOT NULL"
        if column.default is not None:
            seg += f" DEFAULT {column.default}"
        return f"ALTER TABLE {self.qualified_table(table_name)} ADD COLUMN {seg}"

    def would_shrink(
        self,
        old_column: ColumnDef,
        new_column: ColumnDef,
    ) -> bool:
        """True if new column has a smaller length than old (VARCHAR/CHAR)."""
        old_len = _length_from_type_expr(old_column.type_expr)
        new_len = _length_from_type_expr(new_column.type_expr)
        return (
            old_len is not None
            and new_len is not None
            and new_len < old_len
        )

    def alter_column_sql(
        self,
        table_name: QualifiedName,
        old_column: ColumnDef,
        new_column: ColumnDef,
    ) -> str | None:
        """PostgreSQL supports ALTER COLUMN type, SET/DROP NOT NULL, SET DEFAULT."""
        tbl = self.qualified_table(table_name)
        qcol = self._quote(new_column.name)
        stmts: list[str] = []
        if old_column.type_expr != new_column.type_expr:
            stmts.append(f'ALTER TABLE {tbl} ALTER COLUMN {qcol} TYPE {new_column.type_expr}')
        if old_column.nullable != new_column.nullable:
            if new_column.nullable:
                stmts.append(f"ALTER TABLE {tbl} ALTER COLUMN {qcol} DROP NOT NULL")
            else:
                stmts.append(f"ALTER TABLE {tbl} ALTER COLUMN {qcol} SET NOT NULL")
        if old_column.default != new_column.default:
            if new_column.default is None:
                stmts.append(f"ALTER TABLE {tbl} ALTER COLUMN {qcol} DROP DEFAULT")
            else:
                stmts.append(f"ALTER TABLE {tbl} ALTER COLUMN {qcol} SET DEFAULT {new_column.default}")
        if not stmts:
            return None
        return "; ".join(stmts)

    def add_primary_key_sql(
        self,
        table_name: QualifiedName,
        column_names: tuple[str, ...],
    ) -> str | None:
        """PostgreSQL supports ALTER TABLE ... ADD PRIMARY KEY."""
        cols = ", ".join(self._quote(c) for c in column_names)
        return f"ALTER TABLE {self.qualified_table(table_name)} ADD PRIMARY KEY ({cols})"

    def drop_column_sql(
        self,
        table_name: QualifiedName,
        column_name: str,
    ) -> str | None:
        """PostgreSQL supports ALTER TABLE ... DROP COLUMN."""
        return (
            f"ALTER TABLE {self.qualified_table(table_name)} "
            f'DROP COLUMN {self._quote(column_name)}'
        )

    def drop_table_sql(self, table_name: QualifiedName) -> str:
        """Generate DROP TABLE for PostgreSQL."""
        return f"DROP TABLE IF EXISTS {self.qualified_table(table_name)}"

    def drop_unique_sql(
        self,
        table_name: QualifiedName,
        unique: UniqueDef,
    ) -> str | None:
        """PostgreSQL supports DROP CONSTRAINT for unique."""
        if not unique.name:
            return None
        tbl = self.qualified_table(table_name)
        return f"ALTER TABLE {tbl} DROP CONSTRAINT {self._quote(unique.name)}"

    def drop_foreign_key_sql(
        self,
        table_name: QualifiedName,
        fk: ForeignKeyDef,
    ) -> str | None:
        """PostgreSQL supports DROP CONSTRAINT for foreign key."""
        if not fk.name:
            return None
        tbl = self.qualified_table(table_name)
        return f"ALTER TABLE {tbl} DROP CONSTRAINT {self._quote(fk.name)}"

    def drop_check_sql(
        self,
        table_name: QualifiedName,
        check: CheckDef,
    ) -> str | None:
        """PostgreSQL supports DROP CONSTRAINT for check."""
        if not check.name:
            return None
        tbl = self.qualified_table(table_name)
        return f"ALTER TABLE {tbl} DROP CONSTRAINT {self._quote(check.name)}"

    def drop_index_sql(
        self,
        index_name: str,
        table_name: QualifiedName,
    ) -> str:
        """PostgreSQL: DROP INDEX; schema-qualify when table has schema."""
        if table_name.schema:
            return f'DROP INDEX IF EXISTS {self._quote(table_name.schema)}.{self._quote(index_name)}'
        return f"DROP INDEX IF EXISTS {self._quote(index_name)}"

    def create_index_sql(
        self,
        index: IndexDef,
        table_name: QualifiedName,
    ) -> str:
        """Generate CREATE [UNIQUE] INDEX for PostgreSQL."""
        uniq = "UNIQUE " if index.unique else ""
        cols = ", ".join(self._quote(c) for c in index.column_names)
        tbl = self.qualified_table(table_name)
        return f"CREATE {uniq}INDEX {self._quote(index.name)} ON {tbl} ({cols})"
