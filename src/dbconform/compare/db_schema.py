"""
Reflect a live database into internal schema representation.

Uses SQLAlchemy reflection; target_schema filters which tables are included
(required for PostgreSQL; ignored for SQLite). See docs/requirements/01-functional.md
(Database connection, Target schema) and docs/technical/02-architecture.md.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.schema import Table

from dbconform.adapters.model_schema import _extract_table_def
from dbconform.internal.objects import QualifiedName, TableDef


def _dialect_for_connection(connection: Connection):
    """Return our Dialect for the connection's engine (for normalize_reflected_table)."""
    from dbconform.sql_dialect import PostgreSQLDialect, SQLiteDialect

    name = connection.dialect.name
    match name:
        case "sqlite":
            return SQLiteDialect()
        case "postgresql":
            return PostgreSQLDialect()
        case _:
            raise ValueError(f"Unsupported dialect: {name}. Supported: sqlite, postgresql.")


class DatabaseSchema:
    """
    Internal schema derived from a live database via reflection.

    Tables are keyed by QualifiedName. Built by from_connection().
    """

    def __init__(self) -> None:
        self._tables: dict[QualifiedName, TableDef] = {}

    @property
    def tables(self) -> dict[QualifiedName, TableDef]:
        """Tables keyed by qualified name."""
        return self._tables

    @classmethod
    def from_connection(
        cls,
        connection: Connection,
        target_schema: str | None = None,
    ) -> DatabaseSchema:
        """
        Reflect the database and build DatabaseSchema.

        For databases without schemas (e.g. SQLite), target_schema is ignored
        and all tables are reflected. For PostgreSQL, only tables in
        target_schema are reflected (target_schema must be provided).
        """
        dialect = connection.dialect
        metadata = MetaData()
        if target_schema and dialect.name != "sqlite":
            metadata.reflect(bind=connection, schema=target_schema, only=None)
        else:
            metadata.reflect(bind=connection, only=None)
        instance = cls()
        for table in metadata.tables.values():
            if not isinstance(table, Table):
                continue
            schema = table.schema if table.schema is not None else target_schema
            if target_schema is not None and schema != target_schema:
                continue
            table_def = _extract_table_def(table, target_schema, dialect=dialect)
            table_def = _dialect_for_connection(connection).normalize_reflected_table(table_def)
            instance._tables[table_def.name] = table_def
        return instance

    @classmethod
    async def from_connection_async(
        cls,
        connection: AsyncConnection,
        target_schema: str | None = None,
    ) -> DatabaseSchema:
        """
        Reflect the database and build DatabaseSchema using an async connection.

        Uses run_sync to run the sync reflection logic. For databases without schemas
        (e.g. SQLite), target_schema is ignored. For PostgreSQL, only tables in
        target_schema are reflected (target_schema must be provided).
        """

        def _reflect(sync_conn: Connection) -> DatabaseSchema:
            return cls.from_connection(sync_conn, target_schema)

        return await connection.run_sync(_reflect)
