"""
DbConform facade: compare code models to a live database and produce or apply a conform plan.

Accepts connection or credentials and target_schema; exposes compare(models) and apply_changes(models).
See docs/requirements/01-functional.md (Model discovery, Database connection,
Target schema, Conform flow) and docs/technical/02-architecture.md.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from dbconform.adapters import ModelSchema
from dbconform.compare import DatabaseSchema, SchemaDiffer
from dbconform.errors import ConformError
from dbconform.plan import ConformPlan, ConformPlanBuilder
from dbconform.plan.steps import (
    AlterTableStep,
    ConformStep,
    CreateIndexStep,
    CreateTableStep,
    DropTableStep,
    RebuildTableStep,
    SkippedStep,
)
from dbconform.sql_dialect.sqlite_rebuild import build_rebuild_statements
from dbconform.sql_dialect import Dialect, PostgreSQLDialect, SQLiteDialect


def _emit_apply_log(
    step_index: int,
    description: str,
    *,
    emit_log: bool = True,
    log_file: str | None = None,
) -> None:
    """
    Emit a structured (JSON) log line for an applied step (02-non-functional: Observability).

    No secrets or connection data are included. When emit_log is True, writes to stdout.
    Optionally appends to log_file.
    """
    record = {"event": "apply_step", "step_index": step_index, "description": description}
    line = json.dumps(record) + "\n"
    if emit_log:
        sys.stdout.write(line)
        sys.stdout.flush()
    if log_file:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line)


def _step_target_for_error(step: ConformStep, index: int) -> tuple[str, str]:
    """Return (object_type, identifier) for a step (01-functional: Error handling)."""
    match step:
        case DropTableStep() | RebuildTableStep():
            return ("table", str(step.table_name))
        case CreateTableStep() | AlterTableStep() | CreateIndexStep():
            if hasattr(step, "table_name") and step.table_name:
                return ("table", str(step.table_name))
            if getattr(step, "table", None):
                return ("table", str(step.table.name))
    return ("step", f"step_{index}")


def _emit_extra_tables_log(
    extra_tables: list,
    *,
    emit_log: bool = True,
    log_file: str | None = None,
) -> None:
    """
    Emit structured log for extra tables (02-non-functional: Observability).

    When tables exist in DB but not in model, surface them so the user sees drift remains.
    """
    if not extra_tables:
        return
    tables_data = [{"name": t.name, "schema": t.schema} for t in extra_tables]
    record = {"event": "extra_tables", "tables": tables_data}
    line = json.dumps(record) + "\n"
    if emit_log:
        sys.stdout.write(line)
        sys.stdout.flush()
    if log_file:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line)


def _emit_skipped_log(
    skipped: list[SkippedStep],
    *,
    emit_log: bool = True,
    log_file: str | None = None,
) -> None:
    """
    Emit structured log lines for skipped steps (02-non-functional: Observability).

    When drift remains because a step could not be applied (e.g. SQLite constraint add
    with allow_sqlite_table_rebuild=False), these are logged so the user knows.
    """
    for s in skipped:
        record = {
            "event": "skipped_step",
            "description": s.description,
            "reason": s.reason,
            "table": str(s.table_name) if s.table_name else None,
        }
        line = json.dumps(record) + "\n"
        if emit_log:
            sys.stdout.write(line)
            sys.stdout.flush()
        if log_file:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(line)


def _ensure_sqlite_memory_shared(url: str) -> str:
    """
    For SQLite :memory: URLs, add cache=shared so multiple connections share one DB.

    When using credentials with sqlite:///:memory: or sqlite+aiosqlite:///:memory:,
    each engine would otherwise create a fresh empty DB. Shared cache allows
    compare/apply_changes to use the same logical database across calls.
    """
    if ":memory:" not in url or "cache=shared" in url.lower():
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}cache=shared"


def _dialect_for_engine(engine: Engine) -> Dialect:
    """Return the Dialect implementation for the engine."""
    name = engine.dialect.name
    match name:
        case "sqlite":
            return SQLiteDialect()
        case "postgresql":
            return PostgreSQLDialect()
        case _:
            raise ValueError(f"Unsupported dialect: {name}. Supported: sqlite, postgresql.")


def _dialect_for_async_engine(engine: AsyncEngine) -> Dialect:
    """Return the Dialect implementation for an async engine."""
    name = engine.dialect.name
    match name:
        case "sqlite":
            return SQLiteDialect()
        case "postgresql":
            return PostgreSQLDialect()
        case _:
            raise ValueError(f"Unsupported dialect: {name}. Supported: sqlite, postgresql.")


def _apply_plan(
    connection: Connection,
    plan: ConformPlan,
    *,
    commit_per_step: bool = False,
    emit_log: bool = True,
    log_file: str | None = None,
) -> ConformError | None:
    """
    Execute all DDL and data-operation steps in the plan.

    Emits skipped_steps to logs first (drift remains for those). Then runs each step:
    RebuildTableStep uses dialect-specific rebuild logic; others execute step.sql.
    When the connection is already in a transaction, uses a savepoint. Otherwise
    uses connection.begin(). When commit_per_step is False (default), runs in one
    transaction/savepoint; on failure it is rolled back (01-functional).
    On any failure returns ConformError with target_objects set to the step that failed.
    """
    if plan.skipped_steps:
        _emit_skipped_log(
            plan.skipped_steps,
            emit_log=emit_log,
            log_file=log_file,
        )

    if plan.extra_tables:
        _emit_extra_tables_log(
            plan.extra_tables,
            emit_log=emit_log,
            log_file=log_file,
        )

    executable_steps = [s for s in plan.steps if isinstance(s, RebuildTableStep) or (s.sql and s.sql.strip())]
    if not executable_steps:
        return None

    dialect = _dialect_for_engine(connection.engine)

    def run_step(i: int, step: ConformStep) -> ConformError | None:
        try:
            if isinstance(step, RebuildTableStep):
                stmts = build_rebuild_statements(
                    dialect, step.table_name, step.target_table, step.old_table
                )
                for stmt in stmts:
                    connection.execute(text(stmt))
            else:
                assert step.sql
                for part in (p.strip() for p in step.sql.split(";") if p.strip()):
                    connection.execute(text(part))
            _emit_apply_log(i, step.description, emit_log=emit_log, log_file=log_file)
            if commit_per_step:
                connection.commit()
            return None
        except Exception as e:
            e.add_note(f"Step {i}: {step.description}")
            target = _step_target_for_error(step, i)
            return ConformError(target_objects=[target], messages=[str(e)])

    if commit_per_step:
        for i, step in enumerate(executable_steps):
            err = run_step(i, step)
            if err is not None:
                return err
        return None

    def run_all() -> ConformError | None:
        for i, step in enumerate(executable_steps):
            err = run_step(i, step)
            if err is not None:
                return err
        return None

    if connection.in_transaction():
        trans = connection.begin_nested()
        try:
            err = run_all()
            if err is not None:
                trans.rollback()
                return err
            trans.commit()
        except Exception:
            trans.rollback()
            raise
    else:
        with connection.begin():
            err = run_all()
            if err is not None:
                return err
    return None


async def _apply_plan_async(
    connection: AsyncConnection,
    plan: ConformPlan,
    *,
    commit_per_step: bool = False,
    emit_log: bool = True,
    log_file: str | None = None,
) -> ConformError | None:
    """
    Execute all DDL and data-operation steps in the plan (async).

    Same semantics as _apply_plan. Emits skipped_steps, extra_tables, then runs each step
    (including RebuildTableStep for SQLite).
    """
    if plan.skipped_steps:
        _emit_skipped_log(
            plan.skipped_steps,
            emit_log=emit_log,
            log_file=log_file,
        )

    if plan.extra_tables:
        _emit_extra_tables_log(
            plan.extra_tables,
            emit_log=emit_log,
            log_file=log_file,
        )

    executable_steps = [s for s in plan.steps if isinstance(s, RebuildTableStep) or (s.sql and s.sql.strip())]
    if not executable_steps:
        return None

    dialect = _dialect_for_async_engine(connection.engine)

    async def run_step(i: int, step: ConformStep) -> ConformError | None:
        try:
            if isinstance(step, RebuildTableStep):
                stmts = build_rebuild_statements(
                    dialect, step.table_name, step.target_table, step.old_table
                )
                for stmt in stmts:
                    await connection.execute(text(stmt))
            else:
                assert step.sql
                for part in (p.strip() for p in step.sql.split(";") if p.strip()):
                    await connection.execute(text(part))
            _emit_apply_log(i, step.description, emit_log=emit_log, log_file=log_file)
            if commit_per_step:
                await connection.commit()
            return None
        except Exception as e:
            e.add_note(f"Step {i}: {step.description}")
            target = _step_target_for_error(step, i)
            return ConformError(target_objects=[target], messages=[str(e)])

    if commit_per_step:
        for i, step in enumerate(executable_steps):
            err = await run_step(i, step)
            if err is not None:
                return err
        return None

    async def run_all() -> ConformError | None:
        for i, step in enumerate(executable_steps):
            err = await run_step(i, step)
            if err is not None:
                return err
        return None

    if connection.in_transaction():
        trans = await connection.begin_nested()
        try:
            err = await run_all()
            if err is not None:
                await trans.rollback()
                return err
            await trans.commit()
        except Exception:
            await trans.rollback()
            raise
    else:
        async with connection.begin():
            err = await run_all()
            if err is not None:
                return err
    return None


class DbConform:
    """
    Entry point for comparing code models to a database and building or applying a conform plan.

    Pass either an existing connection (caller manages lifecycle) or
    credentials (dbconform opens, runs, closes). target_schema is required
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
        url = _ensure_sqlite_memory_shared(url)
        self._engine = create_engine(url)
        return self._engine.connect()

    def _get_dialect(self, connection: Connection) -> Dialect:
        return _dialect_for_engine(connection.engine)

    def _compare_with_connection(
        self,
        connection: Connection,
        models: type | Sequence[type],
        *,
        allow_drop_extra_tables: bool = False,
        allow_drop_extra_columns: bool = False,
        allow_drop_extra_constraints: bool = True,
        allow_shrink_column: bool = False,
        allow_sqlite_table_rebuild: bool = True,
        report_extra_tables: bool = True,
    ) -> ConformPlan | ConformError:
        """
        Compare models to the database using an open connection; does not close it.

        Returns ConformPlan or ConformError. Used by compare() and apply_changes().
        """
        try:
            dialect = self._get_dialect(connection)
            model_schema = ModelSchema.from_models(
                models,
                target_schema=self._target_schema,
            )
            db_schema = DatabaseSchema.from_connection(connection, self._target_schema)
            differ = SchemaDiffer()
            diff = differ.diff(model_schema, db_schema)
            builder = ConformPlanBuilder(
                dialect,
                allow_drop_extra_tables=allow_drop_extra_tables,
                allow_drop_extra_columns=allow_drop_extra_columns,
                allow_drop_extra_constraints=allow_drop_extra_constraints,
                allow_shrink_column=allow_shrink_column,
                allow_sqlite_table_rebuild=allow_sqlite_table_rebuild,
                report_extra_tables=report_extra_tables,
            )
            return builder.build(diff)
        except Exception as e:
            e.add_note("During compare (model-side internal schema vs database-side internal schema).")
            return ConformError(
                target_objects=[("compare", "schema")],
                messages=[str(e)],
            )

    def compare(
        self,
        models: type | Sequence[type],
        *,
        allow_drop_extra_tables: bool = False,
        allow_drop_extra_columns: bool = False,
        allow_drop_extra_constraints: bool = True,
        allow_shrink_column: bool = False,
        allow_sqlite_table_rebuild: bool = True,
        report_extra_tables: bool = True,
    ) -> ConformPlan | ConformError:
        """
        Compare models to the database and return a conform plan (no apply).

        models: single model class or sequence of model classes (SQLAlchemy/SQLModel).
        Returns ConformPlan with ordered steps and optional extra_tables; or ConformError on failure.
        """
        conn = None
        try:
            conn = self._get_connection()
            return self._compare_with_connection(
                conn,
                models,
                allow_drop_extra_tables=allow_drop_extra_tables,
                allow_drop_extra_columns=allow_drop_extra_columns,
                allow_drop_extra_constraints=allow_drop_extra_constraints,
                allow_shrink_column=allow_shrink_column,
                allow_sqlite_table_rebuild=allow_sqlite_table_rebuild,
                report_extra_tables=report_extra_tables,
            )
        finally:
            if self._own_connection and conn is not None:
                conn.close()
                if self._engine is not None:
                    self._engine.dispose()

    def apply_changes(
        self,
        models: type | Sequence[type],
        *,
        allow_drop_extra_tables: bool = False,
        allow_drop_extra_columns: bool = False,
        allow_drop_extra_constraints: bool = True,
        allow_shrink_column: bool = False,
        allow_sqlite_table_rebuild: bool = True,
        report_extra_tables: bool = True,
        commit_per_step: bool = False,
        emit_log: bool = True,
        log_file: str | None = None,
    ) -> ConformPlan | ConformError:
        """
        Compare models to the database and apply the resulting plan (run DDL and data ops).

        Same comparison options as compare(). On success, returns the ConformPlan that was
        applied. On comparison or apply failure, returns ConformError. By default apply uses
        a single transaction (all-or-nothing rollback on failure); set commit_per_step=True
        to commit after each step (01-functional: Transaction behavior).
        Applied steps are logged as JSON lines to stdout when emit_log is True (default).
        Set emit_log=False to suppress stdout. Pass log_file to also append to a file.
        No secrets are written to logs.
        """
        conn = None
        try:
            conn = self._get_connection()
            plan_or_error = self._compare_with_connection(
                conn,
                models,
                allow_drop_extra_tables=allow_drop_extra_tables,
                allow_drop_extra_columns=allow_drop_extra_columns,
                allow_drop_extra_constraints=allow_drop_extra_constraints,
                allow_shrink_column=allow_shrink_column,
                allow_sqlite_table_rebuild=allow_sqlite_table_rebuild,
                report_extra_tables=report_extra_tables,
            )
            if isinstance(plan_or_error, ConformError):
                return plan_or_error
            plan: ConformPlan = plan_or_error
            if not commit_per_step and not conn.in_transaction():
                conn.commit()
            apply_err = _apply_plan(
                conn,
                plan,
                commit_per_step=commit_per_step,
                emit_log=emit_log,
                log_file=log_file,
            )
            if apply_err is not None:
                return apply_err
            if commit_per_step or self._own_connection or conn.in_transaction():
                conn.commit()
            return plan
        except Exception as e:
            e.add_note("During connection or apply/conform.")
            return ConformError(
                target_objects=[("connection", "conform")],
                messages=[str(e)],
            )
        finally:
            if self._own_connection and conn is not None:
                conn.close()
                if self._engine is not None:
                    self._engine.dispose()


class AsyncDbConform:
    """
    Async entry point for comparing code models to a database and building or applying a conform plan.

    Pass either an existing async connection (caller manages lifecycle) or
    credentials with an async URL (sqlite+aiosqlite://..., postgresql+asyncpg://...).
    target_schema is required for PostgreSQL; omit or None for SQLite.
    """

    def __init__(
        self,
        *,
        async_connection: AsyncConnection | None = None,
        credentials: dict[str, Any] | None = None,
        target_schema: str | None = None,
    ) -> None:
        if async_connection is not None and credentials is not None:
            raise ValueError("Provide async_connection or credentials, not both.")
        if async_connection is None and credentials is None:
            raise ValueError("Provide async_connection or credentials.")
        self._async_connection = async_connection
        self._credentials = credentials
        self._target_schema = target_schema
        self._engine: AsyncEngine | None = None
        self._own_connection = async_connection is None

    def _get_dialect(self, connection: AsyncConnection) -> Dialect:
        return _dialect_for_async_engine(connection.engine)

    async def _compare_with_connection(
        self,
        connection: AsyncConnection,
        models: type | Sequence[type],
        *,
        allow_drop_extra_tables: bool = False,
        allow_drop_extra_columns: bool = False,
        allow_drop_extra_constraints: bool = True,
        allow_shrink_column: bool = False,
        allow_sqlite_table_rebuild: bool = True,
        report_extra_tables: bool = True,
    ) -> ConformPlan | ConformError:
        """
        Compare models to the database using an open async connection; does not close it.

        Returns ConformPlan or ConformError. Used by compare() and apply_changes().
        """
        try:
            dialect = self._get_dialect(connection)
            model_schema = ModelSchema.from_models(
                models,
                target_schema=self._target_schema,
            )
            db_schema = await DatabaseSchema.from_connection_async(connection, self._target_schema)
            differ = SchemaDiffer()
            diff = differ.diff(model_schema, db_schema)
            builder = ConformPlanBuilder(
                dialect,
                allow_drop_extra_tables=allow_drop_extra_tables,
                allow_drop_extra_columns=allow_drop_extra_columns,
                allow_drop_extra_constraints=allow_drop_extra_constraints,
                allow_shrink_column=allow_shrink_column,
                allow_sqlite_table_rebuild=allow_sqlite_table_rebuild,
                report_extra_tables=report_extra_tables,
            )
            return builder.build(diff)
        except Exception as e:
            e.add_note("During compare (model-side internal schema vs database-side internal schema).")
            return ConformError(
                target_objects=[("compare", "schema")],
                messages=[str(e)],
            )

    async def compare(
        self,
        models: type | Sequence[type],
        *,
        allow_drop_extra_tables: bool = False,
        allow_drop_extra_columns: bool = False,
        allow_drop_extra_constraints: bool = True,
        allow_shrink_column: bool = False,
        allow_sqlite_table_rebuild: bool = True,
        report_extra_tables: bool = True,
    ) -> ConformPlan | ConformError:
        """
        Compare models to the database and return a conform plan (no apply).

        models: single model class or sequence of model classes (SQLAlchemy/SQLModel).
        Returns ConformPlan with ordered steps and optional extra_tables; or ConformError on failure.
        """
        if self._async_connection is not None:
            return await self._compare_with_connection(
                self._async_connection,
                models,
                allow_drop_extra_tables=allow_drop_extra_tables,
                allow_drop_extra_columns=allow_drop_extra_columns,
                allow_drop_extra_constraints=allow_drop_extra_constraints,
                allow_shrink_column=allow_shrink_column,
                allow_sqlite_table_rebuild=allow_sqlite_table_rebuild,
                report_extra_tables=report_extra_tables,
            )

        url = self._credentials.get("url")
        if not url:
            raise ValueError("credentials must include 'url'.")
        url = _ensure_sqlite_memory_shared(url)
        self._engine = create_async_engine(url)
        try:
            async with self._engine.connect() as conn:
                return await self._compare_with_connection(
                    conn,
                    models,
                    allow_drop_extra_tables=allow_drop_extra_tables,
                    allow_drop_extra_columns=allow_drop_extra_columns,
                    allow_drop_extra_constraints=allow_drop_extra_constraints,
                    allow_shrink_column=allow_shrink_column,
                    allow_sqlite_table_rebuild=allow_sqlite_table_rebuild,
                    report_extra_tables=report_extra_tables,
                )
        finally:
            await self._engine.dispose()

    async def apply_changes(
        self,
        models: type | Sequence[type],
        *,
        allow_drop_extra_tables: bool = False,
        allow_drop_extra_columns: bool = False,
        allow_drop_extra_constraints: bool = True,
        allow_shrink_column: bool = False,
        allow_sqlite_table_rebuild: bool = True,
        report_extra_tables: bool = True,
        commit_per_step: bool = False,
        emit_log: bool = True,
        log_file: str | None = None,
    ) -> ConformPlan | ConformError:
        """
        Compare models to the database and apply the resulting plan (run DDL and data ops).

        Same comparison options as compare(). On success, returns the ConformPlan that was
        applied. On comparison or apply failure, returns ConformError.
        Set emit_log=False to suppress apply-step logs to stdout.
        """
        if self._async_connection is not None:
            conn = self._async_connection
            plan_or_error = await self._compare_with_connection(
                conn,
                models,
                allow_drop_extra_tables=allow_drop_extra_tables,
                allow_drop_extra_columns=allow_drop_extra_columns,
                allow_drop_extra_constraints=allow_drop_extra_constraints,
                allow_shrink_column=allow_shrink_column,
                allow_sqlite_table_rebuild=allow_sqlite_table_rebuild,
                report_extra_tables=report_extra_tables,
            )
            if isinstance(plan_or_error, ConformError):
                return plan_or_error
            plan = plan_or_error
            if not commit_per_step and not conn.in_transaction():
                await conn.commit()
            apply_err = await _apply_plan_async(
                conn,
                plan,
                commit_per_step=commit_per_step,
                emit_log=emit_log,
                log_file=log_file,
            )
            if apply_err is not None:
                return apply_err
            if commit_per_step or self._own_connection or conn.in_transaction():
                await conn.commit()
            return plan

        url = self._credentials.get("url")
        if not url:
            raise ValueError("credentials must include 'url'.")
        url = _ensure_sqlite_memory_shared(url)
        self._engine = create_async_engine(url)
        try:
            async with self._engine.connect() as conn:
                plan_or_error = await self._compare_with_connection(
                    conn,
                    models,
                    allow_drop_extra_tables=allow_drop_extra_tables,
                    allow_drop_extra_columns=allow_drop_extra_columns,
                    allow_drop_extra_constraints=allow_drop_extra_constraints,
                    allow_shrink_column=allow_shrink_column,
                    allow_sqlite_table_rebuild=allow_sqlite_table_rebuild,
                    report_extra_tables=report_extra_tables,
                )
                if isinstance(plan_or_error, ConformError):
                    return plan_or_error
                plan = plan_or_error
                if not commit_per_step and not conn.in_transaction():
                    await conn.commit()
                apply_err = await _apply_plan_async(
                    conn,
                    plan,
                    commit_per_step=commit_per_step,
                    emit_log=emit_log,
                    log_file=log_file,
                )
                if apply_err is not None:
                    return apply_err
                if commit_per_step or self._own_connection or conn.in_transaction():
                    await conn.commit()
                return plan
        except Exception as e:
            e.add_note("During connection or apply/conform.")
            return ConformError(
                target_objects=[("connection", "conform")],
                messages=[str(e)],
            )
        finally:
            await self._engine.dispose()
