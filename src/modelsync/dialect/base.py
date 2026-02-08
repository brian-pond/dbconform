"""
Abstract dialect interface for DDL generation.

Each backend (SQLite, PostgreSQL, MariaDB) implements identifier quoting
and CREATE/ALTER statements. See docs/requirements/01-functional.md
(Schema parity scope, Identifiers and quoting).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from modelsync.schema.objects import (
    CheckDef,
    ColumnDef,
    ForeignKeyDef,
    IndexDef,
    QualifiedName,
    TableDef,
    UniqueDef,
)


class Dialect(ABC):
    """Base class for backend-specific DDL generation."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Dialect name (e.g. 'sqlite', 'postgresql')."""
        ...

    def quote_identifier(self, name: str) -> str:
        """Quote a single identifier per backend rules (e.g. SQLite double-quote)."""
        return self._quote(name)

    @abstractmethod
    def _quote(self, name: str) -> str:
        """Backend-specific quoting."""
        ...

    def qualified_table(self, table_name: QualifiedName) -> str:
        """Return schema.table or table for use in SQL."""
        if table_name.schema:
            return f"{self._quote(table_name.schema)}.{self._quote(table_name.name)}"
        return self._quote(table_name.name)

    @abstractmethod
    def create_table_sql(self, table: TableDef) -> str:
        """Generate CREATE TABLE statement."""
        ...

    @abstractmethod
    def add_column_sql(self, table_name: QualifiedName, column: ColumnDef) -> str:
        """Generate ALTER TABLE ... ADD COLUMN."""
        ...

    def drop_column_sql(
        self,
        _table_name: QualifiedName,
        _column_name: str,
    ) -> str | None:
        """
        Generate ALTER TABLE ... DROP COLUMN.

        Return None if the dialect does not support dropping columns
        (e.g. older SQLite). Default implementation returns None.
        """
        return None

    def would_shrink(
        self,
        _old_column: ColumnDef,
        _new_column: ColumnDef,
    ) -> bool:
        """
        Return True if applying the new column could shrink existing data
        (e.g. reducing VARCHAR length). Used to guard alter steps when
        allow_shrink_column is False.
        """
        return False

    def alter_column_sql(
        self,
        _table_name: QualifiedName,
        _old_column: ColumnDef,
        _new_column: ColumnDef,
    ) -> str | None:
        """
        Generate ALTER TABLE ... ALTER COLUMN (type/nullability/default).

        Return None if the dialect cannot alter the column in place
        (e.g. SQLite has limited ALTER support).
        """
        return None

    def add_primary_key_sql(
        self,
        _table_name: QualifiedName,
        _column_names: tuple[str, ...],
    ) -> str | None:
        """Generate ALTER TABLE ... ADD PRIMARY KEY. None if not supported."""
        return None

    def add_unique_sql(
        self,
        table_name: QualifiedName,
        unique: UniqueDef,
    ) -> str:
        """Generate ALTER TABLE ... ADD UNIQUE constraint."""
        cols = ", ".join(self._quote(c) for c in unique.column_names)
        name_part = f"CONSTRAINT {self._quote(unique.name)} " if unique.name else ""
        return f"ALTER TABLE {self.qualified_table(table_name)} ADD {name_part}UNIQUE ({cols})"

    def add_foreign_key_sql(
        self,
        table_name: QualifiedName,
        fk: ForeignKeyDef,
    ) -> str:
        """Generate ALTER TABLE ... ADD FOREIGN KEY."""
        cols = ", ".join(self._quote(c) for c in fk.column_names)
        ref_cols = ", ".join(self._quote(c) for c in fk.ref_column_names)
        ref = self.qualified_table(fk.ref_table)
        name_part = f"CONSTRAINT {self._quote(fk.name)} " if fk.name else ""
        tbl = self.qualified_table(table_name)
        return (
            f"ALTER TABLE {tbl} ADD {name_part}FOREIGN KEY ({cols}) "
            f"REFERENCES {ref} ({ref_cols})"
        )

    def add_check_sql(
        self,
        table_name: QualifiedName,
        check: CheckDef,
    ) -> str:
        """Generate ALTER TABLE ... ADD CHECK."""
        name_part = f"CONSTRAINT {self._quote(check.name)} " if check.name else ""
        tbl = self.qualified_table(table_name)
        return f"ALTER TABLE {tbl} ADD {name_part}CHECK ({check.expression})"

    def create_index_sql(
        self,
        index: IndexDef,
        table_name: QualifiedName,
    ) -> str:
        """Generate CREATE [UNIQUE] INDEX."""
        uniq = "UNIQUE " if index.unique else ""
        cols = ", ".join(self._quote(c) for c in index.column_names)
        tbl = self.qualified_table(table_name)
        return f"CREATE {uniq}INDEX {self._quote(index.name)} ON {tbl} ({cols})"

    def drop_table_sql(self, table_name: QualifiedName) -> str:
        """Generate DROP TABLE. Used when allow_drop_table=True (01-functional: Opt-in flags)."""
        return f"DROP TABLE IF EXISTS {self.qualified_table(table_name)}"

    def drop_unique_sql(
        self,
        table_name: QualifiedName,
        unique: UniqueDef,
    ) -> str | None:
        """Generate ALTER TABLE ... DROP CONSTRAINT for unique. None if not supported."""
        if not unique.name:
            return None
        tbl = self.qualified_table(table_name)
        return f"ALTER TABLE {tbl} DROP CONSTRAINT {self._quote(unique.name)}"

    def drop_foreign_key_sql(
        self,
        table_name: QualifiedName,
        fk: ForeignKeyDef,
    ) -> str | None:
        """Generate ALTER TABLE ... DROP CONSTRAINT for foreign key. None if not supported."""
        if not fk.name:
            return None
        tbl = self.qualified_table(table_name)
        return f"ALTER TABLE {tbl} DROP CONSTRAINT {self._quote(fk.name)}"

    def drop_check_sql(
        self,
        table_name: QualifiedName,
        check: CheckDef,
    ) -> str | None:
        """Generate ALTER TABLE ... DROP CONSTRAINT for check. None if not supported."""
        if not check.name:
            return None
        tbl = self.qualified_table(table_name)
        return f"ALTER TABLE {tbl} DROP CONSTRAINT {self._quote(check.name)}"

    def drop_index_sql(
        self,
        index_name: str,
        table_name: QualifiedName,
    ) -> str:
        """Generate DROP INDEX."""
        tbl = self.qualified_table(table_name)
        return f"DROP INDEX IF EXISTS {self._quote(index_name)}"
