"""
Integration tests: PostgreSQL-specific neutral type mapping.

Traceability: docs/requirements/01-functional.md (Schema parity, Backends).
GitHub #3 (DDL emits BYTEA), #7 (reflected BYTEA normalizes to BLOB),
#4 (JSONB), #5 (TIMESTAMPTZ), #10 (TypeDecorator dialect resolution).
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, TypeDecorator, create_engine, select, text
from sqlalchemy.dialects.postgresql import BYTEA, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

import dbconform
from dbconform.plan import CreateTableStep


class _BinaryBase(DeclarativeBase):
    """Declarative base for binary column integration tests."""


class BrokerMessage(_BinaryBase):
    """Model with PostgreSQL BYTEA column."""

    __tablename__ = "broker_message"

    message_id: Mapped[str] = mapped_column(primary_key=True)
    payload: Mapped[bytes] = mapped_column(BYTEA, nullable=False)


class BrokerQueue(_BinaryBase):
    """Model with JSONB and TIMESTAMPTZ columns (GitHub #4, #5)."""

    __tablename__ = "broker_queue"

    queue_name: Mapped[str] = mapped_column(primary_key=True)
    headers: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UtcDateTime(TypeDecorator):
    """SQLite: ISO string; PostgreSQL: timestamptz (GitHub #10 repro)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(32))
        return dialect.type_descriptor(DateTime(timezone=True))


class TaskRunGroup(_BinaryBase):
    """Model with TypeDecorator column that maps per dialect."""

    __tablename__ = "task_run_groups"

    run_group_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scheduled_for: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class AttemptBlob(_BinaryBase):
    """BTU-style table: TypeDecorator timestamptz column (GitHub #10 migration)."""

    __tablename__ = "attempt_blobs"

    attempt_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


def _pg_column_type(url: str, schema: str, table: str, column: str) -> str:
    """Return PostgreSQL data_type for a column from information_schema."""
    engine = create_engine(url)
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = :table AND column_name = :column"
            ),
            {"schema": schema, "table": table, "column": column},
        ).one()
    engine.dispose()
    return row[0]


def test_apply_bytea_column_postgres(empty_postgres_db: tuple[str, str]) -> None:
    """Apply creates BYTEA column; re-compare is stable (GitHub #3, #7)."""
    url, schema = empty_postgres_db
    conform = dbconform.DbConform(credentials={"url": url}, target_schema=schema)
    plan = conform.compare([BrokerMessage])
    assert not isinstance(plan, dbconform.ConformError)
    assert any(isinstance(s, CreateTableStep) for s in plan.steps)

    result = conform.apply_changes([BrokerMessage], emit_log=False)
    assert not isinstance(result, dbconform.ConformError)

    assert _pg_column_type(url, schema, "broker_message", "payload") == "bytea"

    recompare = conform.compare([BrokerMessage])
    assert not isinstance(recompare, dbconform.ConformError)
    assert len(recompare.steps) == 0


def test_apply_bytea_column_sqlite(empty_sqlite_db: tuple) -> None:
    """BLOB neutral type applies on SQLite without regression."""
    _path, url = empty_sqlite_db
    conform = dbconform.DbConform(credentials={"url": url}, target_schema=None)
    result = conform.apply_changes([BrokerMessage], emit_log=False)
    assert not isinstance(result, dbconform.ConformError)
    recompare = conform.compare([BrokerMessage])
    assert len(recompare.steps) == 0


def test_apply_jsonb_and_timestamptz_postgres(empty_postgres_db: tuple[str, str]) -> None:
    """Apply creates JSONB and TIMESTAMPTZ columns; re-compare is stable (GitHub #4, #5)."""
    url, schema = empty_postgres_db
    conform = dbconform.DbConform(credentials={"url": url}, target_schema=schema)
    plan = conform.compare([BrokerQueue])
    assert not isinstance(plan, dbconform.ConformError)
    assert any(isinstance(s, CreateTableStep) for s in plan.steps)

    result = conform.apply_changes([BrokerQueue], emit_log=False)
    assert not isinstance(result, dbconform.ConformError)

    assert _pg_column_type(url, schema, "broker_queue", "headers") == "jsonb"
    assert _pg_column_type(url, schema, "broker_queue", "created_at") == "timestamp with time zone"

    recompare = conform.compare([BrokerQueue])
    assert not isinstance(recompare, dbconform.ConformError)
    assert len(recompare.steps) == 0


def test_apply_type_decorator_timestamptz_postgres(empty_postgres_db: tuple[str, str]) -> None:
    """TypeDecorator with load_dialect_impl creates TIMESTAMPTZ on PostgreSQL (GitHub #10)."""
    url, schema = empty_postgres_db
    conform = dbconform.DbConform(credentials={"url": url}, target_schema=schema)
    plan = conform.compare([TaskRunGroup])
    assert not isinstance(plan, dbconform.ConformError)
    assert any(isinstance(s, CreateTableStep) for s in plan.steps)

    result = conform.apply_changes([TaskRunGroup], emit_log=False)
    assert not isinstance(result, dbconform.ConformError)

    assert _pg_column_type(url, schema, "task_run_groups", "scheduled_for") == (
        "timestamp with time zone"
    )

    recompare = conform.compare([TaskRunGroup])
    assert not isinstance(recompare, dbconform.ConformError)
    assert len(recompare.steps) == 0

    engine = create_engine(url)
    with Session(engine) as session:
        session.execute(
            select(TaskRunGroup).where(
                TaskRunGroup.scheduled_for <= datetime.now(timezone.utc)
            )
        )
    engine.dispose()


def test_alter_varchar_to_timestamptz_postgres_issue10_migration(
    empty_postgres_db: tuple[str, str],
) -> None:
    """
    Migrate VARCHAR column (wrong DDL from issue #10) to TIMESTAMPTZ with USING cast.

    Simulates BTU tables created before TypeDecorator fix; apply_changes must succeed.
    Traceability: docs/requirements/01-functional.md (Data operations: type changes).
    """
    url, schema = empty_postgres_db
    engine = create_engine(url)
    ts = "2024-06-01T12:00:00+00:00"
    with engine.connect() as conn:
        conn.execute(
            text(
                f'CREATE TABLE "{schema}"."attempt_blobs" ('
                f'"attempt_id" VARCHAR(36) PRIMARY KEY, '
                f'"created_at" VARCHAR(32) NOT NULL)'
            )
        )
        conn.execute(
            text(
                f'INSERT INTO "{schema}"."attempt_blobs" ("attempt_id", "created_at") '
                f"VALUES ('a1', :ts)"
            ),
            {"ts": ts},
        )
        conn.commit()
    engine.dispose()

    conform = dbconform.DbConform(credentials={"url": url}, target_schema=schema)
    plan = conform.compare([AttemptBlob])
    assert not isinstance(plan, dbconform.ConformError)
    assert "USING" in plan.sql()
    assert "TIMESTAMPTZ" in plan.sql()

    result = conform.apply_changes([AttemptBlob], emit_log=False)
    assert not isinstance(result, dbconform.ConformError)

    assert _pg_column_type(url, schema, "attempt_blobs", "created_at") == (
        "timestamp with time zone"
    )

    recompare = conform.compare([AttemptBlob])
    assert not isinstance(recompare, dbconform.ConformError)
    assert len(recompare.steps) == 0

    engine = create_engine(url)
    with Session(engine) as session:
        session.execute(
            select(AttemptBlob).where(AttemptBlob.created_at <= datetime.now(timezone.utc))
        )
    engine.dispose()
