"""
SQLite dialect: double-quoted identifiers, CREATE TABLE, ADD COLUMN.

SQLite does not support ALTER COLUMN type or ADD PRIMARY KEY after creation.
See docs/requirements/01-functional.md (Schema parity scope).
"""

from __future__ import annotations

from dbconform.internal.objects import (
    CheckDef,
    ColumnDef,
    ForeignKeyDef,
    QualifiedName,
    TableDef,
    UniqueDef,
)
from dbconform.sql_dialect.base import Dialect


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
            and any(c.autoincrement and c.name in table.primary_key.column_names for c in table.columns)
        )
        for col in table.columns:
            seg = f"{self._quote(col.name)} {col.data_type_name}"
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
        seg = f"{self._quote(column.name)} {column.data_type_name}"
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
        old_len = self._parse_varchar_length(old_column.data_type_name)
        new_len = self._parse_varchar_length(new_column.data_type_name)
        return old_len is not None and new_len is not None and new_len < old_len

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

    def drop_column_sql(
        self,
        table_name: QualifiedName,
        column_name: str,
    ) -> str | None:
        """SQLite 3.35+ supports ALTER TABLE ... DROP COLUMN."""
        return f"ALTER TABLE {self.qualified_table(table_name)} DROP COLUMN {self._quote(column_name)}"

    def drop_table_sql(self, table_name: QualifiedName) -> str:
        """Generate DROP TABLE for SQLite."""
        return f"DROP TABLE IF EXISTS {self.qualified_table(table_name)}"

    def drop_unique_sql(
        self,
        _table_name: QualifiedName,
        _unique: UniqueDef,
    ) -> str | None:
        """SQLite does not support DROP CONSTRAINT for unique."""
        return None

    def drop_foreign_key_sql(
        self,
        _table_name: QualifiedName,
        _fk: ForeignKeyDef,
    ) -> str | None:
        """SQLite does not support DROP CONSTRAINT for foreign key."""
        return None

    def drop_check_sql(
        self,
        _table_name: QualifiedName,
        _check: CheckDef,
    ) -> str | None:
        """SQLite does not support DROP CONSTRAINT for check."""
        return None
