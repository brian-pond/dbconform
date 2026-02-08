"""
ModelSync facade: compare code models to a live database and produce or apply a sync plan.

Accepts connection or credentials and target_schema; exposes compare(models) and do_sync(models).
See docs/requirements/01-functional.md (Model discovery, Database connection,
Target schema, Sync flow) and docs/technical/02-architecture.md.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from modelsync.dialect import Dialect, SQLiteDialect
from modelsync.errors import SyncError
from modelsync.plan import SyncPlan, SyncPlanBuilder
from modelsync.plan.steps import (
    AlterTableStep,
    CreateIndexStep,
    CreateTableStep,
    DropTableStep,
    SyncStep,
)
from modelsync.schema import DatabaseSchema, ModelSchema
from modelsync.schema.diff import SchemaDiffer


def _emit_apply_log(
    step_index: int,
    description: str,
    *,
    log_file: str | None = None,
) -> None:
    """
    Emit a structured (JSON) log line for an applied step (02-non-functional: Observability).

    No secrets or connection data are included. Writes to stdout and optionally to log_file.
    """
    record = {"event": "apply_step", "step_index": step_index, "description": description}
    line = json.dumps(record) + "\n"
    sys.stdout.write(line)
    sys.stdout.flush()
    if log_file:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line)


def _step_target(step: SyncStep, index: int) -> tuple[str, str]:
    """Return (object_type, identifier) for a step (01-functional: Error handling)."""
    if isinstance(step, DropTableStep):
        return ("table", str(step.table_name))
    if isinstance(step, (CreateTableStep, AlterTableStep, CreateIndexStep)):
        if hasattr(step, "table_name") and step.table_name:
            return ("table", str(step.table_name))
        if getattr(step, "table", None):
            return ("table", str(step.table.name))
    return ("step", f"step_{index}")


def _dialect_for_engine(engine: Engine) -> Dialect:
    """Return the Dialect implementation for the engine."""
    name = engine.dialect.name
    if name == "sqlite":
        return SQLiteDialect()
    raise ValueError(f"Unsupported dialect: {name}. Supported: sqlite.")


def _apply_plan(
    connection: Connection,
    plan: SyncPlan,
    *,
    commit_per_step: bool = False,
    log_file: str | None = None,
) -> SyncError | None:
    """
    Execute all DDL and data-operation statements in the plan.

    When commit_per_step is False (default), runs in one transaction; on failure
    the transaction is rolled back (01-functional: Transaction behavior).
    When commit_per_step is True, commits after each step.
    On any failure returns SyncError with target_objects set to the step that failed.
    """
    statements = plan.statements()
    if not statements:
        return None
    steps_with_sql = [s for s in plan.steps if s.sql and s.sql.strip()]

    def run_step(i: int, sql: str) -> SyncError | None:
        try:
            connection.execute(text(sql))
            step = steps_with_sql[i] if i < len(steps_with_sql) else None
            desc = step.description if step else f"step_{i}"
            _emit_apply_log(i, desc, log_file=log_file)
            if commit_per_step:
                connection.commit()
            return None
        except Exception as e:
            step = steps_with_sql[i] if i < len(steps_with_sql) else None
            target = _step_target(step, i) if step else ("step", f"step_{i}")
            return SyncError(target_objects=[target], messages=[str(e)])

    if commit_per_step:
        for i, sql in enumerate(statements):
            err = run_step(i, sql)
            if err is not None:
                return err
        return None
    with connection.begin():
        for i, sql in enumerate(statements):
            err = run_step(i, sql)
            if err is not None:
                return err
    return None


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
        allow_drop_constraint: bool = True,
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
                allow_drop_constraint=allow_drop_constraint,
                allow_shrink_column=allow_shrink_column,
                report_extra_tables=report_extra_tables,
            )
            return builder.build(diff)
        except Exception as e:
            return SyncError(
                target_objects=[("compare", "schema")],
                messages=[str(e)],
            )

    def compare(
        self,
        models: type | Sequence[type],
        *,
        allow_drop_table: bool = False,
        allow_drop_column: bool = False,
        allow_drop_constraint: bool = True,
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
                allow_drop_constraint=allow_drop_constraint,
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
        allow_drop_constraint: bool = True,
        allow_shrink_column: bool = False,
        report_extra_tables: bool = True,
        commit_per_step: bool = False,
        log_file: str | None = None,
    ) -> SyncPlan | SyncError:
        """
        Compare models to the database and apply the resulting plan (run DDL and data ops).

        Same comparison options as compare(). On success, returns the SyncPlan that was
        applied. On comparison or apply failure, returns SyncError. By default apply uses
        a single transaction (all-or-nothing rollback on failure); set commit_per_step=True
        to commit after each step (01-functional: Transaction behavior).
        Applied steps are logged as JSON lines to stdout (02-non-functional: Observability);
        pass log_file to also append to a file. No secrets are written to logs.
        """
        conn = None
        try:
            conn = self._get_connection()
            plan_or_error = self._compare_with_connection(
                conn,
                models,
                allow_drop_table=allow_drop_table,
                allow_drop_column=allow_drop_column,
                allow_drop_constraint=allow_drop_constraint,
                allow_shrink_column=allow_shrink_column,
                report_extra_tables=report_extra_tables,
            )
            if isinstance(plan_or_error, SyncError):
                return plan_or_error
            plan = plan_or_error
            if not commit_per_step:
                conn.commit()
            apply_err = _apply_plan(
                conn,
                plan,
                commit_per_step=commit_per_step,
                log_file=log_file,
            )
            if apply_err is not None:
                return apply_err
            if commit_per_step:
                conn.commit()
            return plan
        except Exception as e:
            return SyncError(
                target_objects=[("connection", "sync")],
                messages=[str(e)],
            )
        finally:
            if self._own_connection and conn is not None:
                conn.close()
                if self._engine is not None:
                    self._engine.dispose()
