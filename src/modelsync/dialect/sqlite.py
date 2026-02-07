"""
SQLite dialect: double-quoted identifiers, CREATE TABLE, ADD COLUMN.

SQLite does not support ALTER COLUMN type or ADD PRIMARY KEY after creation.
See docs/requirements/01-functional.md (Schema parity scope).
"""

from __future__ import annotations

from modelsync.dialect.base import Dialect
from modelsync.schema.objects import (
    ColumnDef,
    QualifiedName,
    TableDef,
)


class SQLiteDialect(Dialect):
    """DDL generation for SQLite."""

    @property
    def name(self) -> str:
        return "sqlite"

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
            seg = f"{self._quote(col.name)} {col.type_expr}"
            if not col.nullable:
                seg += " NOT NULL"
            if col.default is not None:
                seg += f" DEFAULT {col.default}"
            if pk_inline and table.primary_key and col.name in table.primary_key.column_names:
                seg += " PRIMARY KEY AUTOINCREMENT"
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
        """SQLite supports ALTER TABLE ... ADD COLUMN."""
        seg = f"{self._quote(column.name)} {column.type_expr}"
        if not column.nullable:
            seg += " NOT NULL"
        if column.default is not None:
            seg += f" DEFAULT {column.default}"
        return f"ALTER TABLE {self.qualified_table(table_name)} ADD COLUMN {seg}"

    def alter_column_sql(
        self,
        _table_name: QualifiedName,
        _old_column: ColumnDef,
        _new_column: ColumnDef,
    ) -> str | None:
        """SQLite does not support altering column type or nullability in place."""
        return None

    def add_primary_key_sql(
        self,
        _table_name: QualifiedName,
        _column_names: tuple[str, ...],
    ) -> str | None:
        """SQLite does not support ADD PRIMARY KEY via ALTER TABLE."""
        return None
