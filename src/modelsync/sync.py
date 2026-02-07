"""
ModelSync facade: compare code models to a live database and produce a sync plan.

Accepts connection or credentials and target_schema; exposes compare(models).
See docs/requirements/01-functional.md (Model discovery, Database connection,
Target schema, Sync flow) and docs/technical/02-architecture.md.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine

from modelsync.dialect import Dialect, SQLiteDialect
from modelsync.errors import SyncError
from modelsync.plan import SyncPlan, SyncPlanBuilder
from modelsync.schema import DatabaseSchema, ModelSchema
from modelsync.schema.diff import SchemaDiffer


def _dialect_for_engine(engine: Engine) -> Dialect:
    """Return the Dialect implementation for the engine."""
    name = engine.dialect.name
    if name == "sqlite":
        return SQLiteDialect()
    raise ValueError(f"Unsupported dialect: {name}. Supported: sqlite.")


class ModelSync:
    """
    Entry point for comparing code models to a database and building a sync plan.

    Pass either an existing connection (caller manages lifecycle) or
    credentials (modelsync opens, runs, closes). target_schema is required
    for PostgreSQL; omit or None for SQLite.
    """

    def __init__(
        self,
        *,
        connection: Connection | None = None,
        credentials: dict[str, Any] | None = None,
        target_schema: str | None = None,
    ) -> None:
        if connection is not None and credentials is not None:
            raise ValueError("Provide connection or credentials, not both.")
        if connection is None and credentials is None:
            raise ValueError("Provide connection or credentials.")
        self._connection = connection
        self._credentials = credentials
        self._target_schema = target_schema
        self._engine: Engine | None = None
        self._own_connection = connection is None

    def _get_connection(self) -> Connection:
        if self._connection is not None:
            return self._connection
        url = self._credentials.get("url")
        if not url:
            raise ValueError("credentials must include 'url'.")
        self._engine = create_engine(url)
        return self._engine.connect()

    def _get_dialect(self, connection: Connection) -> Dialect:
        return _dialect_for_engine(connection.engine)

    def compare(
        self,
        models: type | Sequence[type],
        *,
        allow_drop_table: bool = False,
        report_extra_tables: bool = True,
    ) -> SyncPlan | SyncError:
        """
        Compare models to the database and return a sync plan (no apply).

        models: single model class or sequence of model classes (SQLAlchemy/SQLModel).
        Returns SyncPlan with ordered steps and optional extra_tables; or SyncError on failure.
        """
        conn = None
        try:
            conn = self._get_connection()
            dialect = self._get_dialect(conn)
            model_schema = ModelSchema.from_models(
                models,
                dialect=conn.dialect,
                target_schema=self._target_schema,
            )
            db_schema = DatabaseSchema.from_connection(conn, self._target_schema)
            differ = SchemaDiffer()
            diff = differ.diff(model_schema, db_schema)
            builder = SyncPlanBuilder(
                dialect,
                allow_drop_table=allow_drop_table,
                report_extra_tables=report_extra_tables,
            )
            return builder.build(diff)
        except Exception as e:
            return SyncError(
                target_objects=[],
                messages=[str(e)],
            )
        finally:
            if self._own_connection and conn is not None:
                conn.close()
                if self._engine is not None:
                    self._engine.dispose()
