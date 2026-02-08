"""
ModelSync facade: compare code models to a live database and produce or apply a sync plan.

Accepts connection or credentials and target_schema; exposes compare(models) and do_sync(models).
See docs/requirements/01-functional.md (Model discovery, Database connection,
Target schema, Sync flow) and docs/technical/02-architecture.md.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import create_engine, text
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


def _apply_plan(connection: Connection, plan: SyncPlan) -> None:
    """
    Execute all DDL and data-operation statements in the plan in one transaction.

    On any failure, the transaction is rolled back (all-or-nothing per
    docs/requirements/01-functional.md — Transaction behavior).
    """
    statements = plan.statements()
    if not statements:
        return
    with connection.begin():
        for sql in statements:
            connection.execute(text(sql))


class ModelSync:
    """
    Entry point for comparing code models to a database and building or applying a sync plan.

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

    def _compare_with_connection(
        self,
        connection: Connection,
        models: type | Sequence[type],
        *,
        allow_drop_table: bool = False,
        allow_drop_column: bool = False,
        allow_shrink_column: bool = False,
        report_extra_tables: bool = True,
    ) -> SyncPlan | SyncError:
        """
        Compare models to the database using an open connection; does not close it.

        Returns SyncPlan or SyncError. Used by compare() and do_sync().
        """
        try:
            dialect = self._get_dialect(connection)
            model_schema = ModelSchema.from_models(
                models,
                dialect=connection.dialect,
                target_schema=self._target_schema,
            )
            db_schema = DatabaseSchema.from_connection(connection, self._target_schema)
            differ = SchemaDiffer()
            diff = differ.diff(model_schema, db_schema)
            builder = SyncPlanBuilder(
                dialect,
                allow_drop_table=allow_drop_table,
                allow_drop_column=allow_drop_column,
                allow_shrink_column=allow_shrink_column,
                report_extra_tables=report_extra_tables,
            )
            return builder.build(diff)
        except Exception as e:
            return SyncError(
                target_objects=[],
                messages=[str(e)],
            )

    def compare(
        self,
        models: type | Sequence[type],
        *,
        allow_drop_table: bool = False,
        allow_drop_column: bool = False,
        allow_shrink_column: bool = False,
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
            return self._compare_with_connection(
                conn,
                models,
                allow_drop_table=allow_drop_table,
                allow_drop_column=allow_drop_column,
                allow_shrink_column=allow_shrink_column,
                report_extra_tables=report_extra_tables,
            )
        finally:
            if self._own_connection and conn is not None:
                conn.close()
                if self._engine is not None:
                    self._engine.dispose()

    def do_sync(
        self,
        models: type | Sequence[type],
        *,
        allow_drop_table: bool = False,
        allow_drop_column: bool = False,
        allow_shrink_column: bool = False,
        report_extra_tables: bool = True,
    ) -> SyncPlan | SyncError:
        """
        Compare models to the database and apply the resulting plan (run DDL and data ops).

        Same comparison options as compare(). On success, returns the SyncPlan that was
        applied. On comparison or apply failure, returns SyncError; apply uses a single
        transaction (all-or-nothing rollback on failure). See docs/requirements/01-functional.md
        (Sync flow, Transaction behavior).
        """
        conn = None
        try:
            conn = self._get_connection()
            plan_or_error = self._compare_with_connection(
                conn,
                models,
                allow_drop_table=allow_drop_table,
                allow_drop_column=allow_drop_column,
                allow_shrink_column=allow_shrink_column,
                report_extra_tables=report_extra_tables,
            )
            if isinstance(plan_or_error, SyncError):
                return plan_or_error
            plan = plan_or_error
            conn.commit()
            _apply_plan(conn, plan)
            return plan
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
