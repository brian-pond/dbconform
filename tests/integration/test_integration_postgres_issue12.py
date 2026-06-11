"""
Integration tests for GitHub #12: NOT NULL backfill, CHECK DDL parentheses, re-compare parity.

Traceability: docs/requirements/01-functional.md (Data operations, Schema parity).
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Integer, MetaData, String, Table, create_engine, text
from sqlalchemy.orm import DeclarativeBase

import dbconform
from dbconform.errors import ConformError
from dbconform.plan import AlterTableStep


class _Issue12Base(DeclarativeBase):
    """Declarative base for GitHub #12 integration tests."""


class BrokerMessageDestination(_Issue12Base):
    """Model with top-level OR CHECK (GitHub #12 Gap 2)."""

    __tablename__ = "broker_message"
    __table_args__ = (
        CheckConstraint(
            "(destination = 'general' AND bucket_id IS NULL) OR "
            "(destination = 'bucket' AND bucket_id IS NOT NULL)",
            name="broker_message_destination_bucket_ck",
        ),
        {"schema": "broker"},
    )

    message_id = Column(Integer, primary_key=True)
    destination = Column(String(50), nullable=False)
    bucket_id = Column(Integer, nullable=True)


class BrokerWorkerSentinel(_Issue12Base):
    """Model with boolean-equality CHECK (GitHub #12 Gap 3)."""

    __tablename__ = "broker_worker"
    __table_args__ = (
        CheckConstraint(
            "(dispatch_role = 'system') = (NOT is_assignable)",
            name="broker_worker_sentinel_ck",
        ),
        {"schema": "broker"},
    )

    worker_id = Column(Integer, primary_key=True)
    dispatch_role = Column(String(50), nullable=False)
    is_assignable = Column(Boolean, nullable=False)


def _create_broker_message_table(url: str) -> None:
    """Create broker_message without CHECK constraints."""
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                'CREATE TABLE "broker"."broker_message" ('
                "message_id INTEGER PRIMARY KEY, "
                "destination VARCHAR(50) NOT NULL, "
                "bucket_id INTEGER)"
            )
        )
        conn.execute(
            text(
                'INSERT INTO "broker"."broker_message" '
                "(message_id, destination, bucket_id) VALUES (1, 'general', NULL)"
            )
        )
        conn.commit()
    engine.dispose()


def _create_broker_worker_table(url: str) -> None:
    """Create broker_worker without CHECK constraints."""
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                'CREATE TABLE "broker"."broker_worker" ('
                "worker_id INTEGER PRIMARY KEY, "
                "dispatch_role VARCHAR(50) NOT NULL, "
                "is_assignable BOOLEAN NOT NULL)"
            )
        )
        conn.execute(
            text(
                'INSERT INTO "broker"."broker_worker" '
                "(worker_id, dispatch_role, is_assignable) VALUES (1, 'system', false)"
            )
        )
        conn.commit()
    engine.dispose()


def test_postgres_or_check_apply_and_recompare(
    postgres_broker_schema_db: tuple[str, str],
) -> None:
    """ADD CHECK with top-level OR emits valid SQL and achieves parity (GitHub #12 Gap 2)."""
    url, schema = postgres_broker_schema_db
    _create_broker_message_table(url)

    conform = dbconform.DbConform(credentials={"url": url}, target_schema=schema)
    plan = conform.compare([BrokerMessageDestination])
    assert not isinstance(plan, ConformError), str(plan)
    add_steps = [s for s in plan.steps if isinstance(s, AlterTableStep)]
    assert len(add_steps) == 1
    sql = add_steps[0].sql or ""
    assert "CHECK (" in sql
    assert sql.index("CHECK (") < sql.index(" OR ")

    result = conform.apply_changes([BrokerMessageDestination])
    assert not isinstance(result, ConformError), str(result)

    recompare = conform.compare([BrokerMessageDestination])
    assert not isinstance(recompare, ConformError), str(recompare)
    assert len(recompare.steps) == 0


def test_postgres_boolean_equality_check_apply_and_recompare(
    postgres_broker_schema_db: tuple[str, str],
) -> None:
    """ADD CHECK with ``(A) = (B)`` emits valid SQL and achieves parity (GitHub #12 Gap 3)."""
    url, schema = postgres_broker_schema_db
    _create_broker_worker_table(url)

    conform = dbconform.DbConform(credentials={"url": url}, target_schema=schema)
    plan = conform.compare([BrokerWorkerSentinel])
    assert not isinstance(plan, ConformError), str(plan)
    add_steps = [s for s in plan.steps if isinstance(s, AlterTableStep)]
    assert len(add_steps) == 1
    sql = add_steps[0].sql or ""
    assert "CHECK ((" in sql or "CHECK ((dispatch_role" in sql

    result = conform.apply_changes([BrokerWorkerSentinel])
    assert not isinstance(result, ConformError), str(result)

    recompare = conform.compare([BrokerWorkerSentinel])
    assert not isinstance(recompare, ConformError), str(recompare)
    assert len(recompare.steps) == 0


def test_postgres_not_null_backfill_blocked_by_default(
    postgres_broker_schema_db: tuple[str, str],
) -> None:
    """ADD NOT NULL on non-empty table is blocked without allow_not_null_backfill (Gap 1)."""
    url, schema = postgres_broker_schema_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                'CREATE TABLE "broker"."broker_bucket" ('
                "bucket_id INTEGER PRIMARY KEY, "
                "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
        )
        conn.execute(
            text('INSERT INTO "broker"."broker_bucket" (bucket_id) VALUES (1)')
        )
        conn.commit()
    engine.dispose()

    metadata = MetaData(schema="broker")

    class BrokerBucket:
        __table__ = Table(
            "broker_bucket",
            metadata,
            Column("bucket_id", Integer, primary_key=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column(
                "updated_at",
                DateTime(timezone=True),
                nullable=False,
                info={"dbconform_backfill": "created_at"},
            ),
        )

    conform = dbconform.DbConform(credentials={"url": url}, target_schema=schema)
    result = conform.compare([BrokerBucket])
    assert isinstance(result, ConformError)
    assert result.plan is not None
    assert result.plan.has_blocking_skipped_steps()
    assert any("allow_not_null_backfill=False" in s.reason for s in result.plan.skipped_steps)


def test_postgres_not_null_backfill_apply_and_recompare(
    postgres_broker_schema_db: tuple[str, str],
) -> None:
    """Multi-step NOT NULL backfill on non-empty table (GitHub #12 Gap 1)."""
    url, schema = postgres_broker_schema_db
    engine = create_engine(url)
    created = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    with engine.connect() as conn:
        conn.execute(
            text(
                'CREATE TABLE "broker"."broker_bucket" ('
                "bucket_id INTEGER PRIMARY KEY, "
                "created_at TIMESTAMPTZ NOT NULL)"
            )
        )
        conn.execute(
            text(
                'INSERT INTO "broker"."broker_bucket" (bucket_id, created_at) '
                "VALUES (1, :created)"
            ),
            {"created": created},
        )
        conn.commit()
    engine.dispose()

    metadata = MetaData(schema="broker")

    class BrokerBucket:
        __table__ = Table(
            "broker_bucket",
            metadata,
            Column("bucket_id", Integer, primary_key=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column(
                "updated_at",
                DateTime(timezone=True),
                nullable=False,
                info={"dbconform_backfill": "created_at"},
            ),
        )

    conform = dbconform.DbConform(credentials={"url": url}, target_schema=schema)
    result = conform.apply_changes(
        [BrokerBucket],
        allow_not_null_backfill=True,
    )
    assert not isinstance(result, ConformError), str(result)
    assert any("updated_at" in (s.description or "") for s in result.steps)

    engine = create_engine(url)
    with engine.connect() as conn:
        row = conn.execute(
            text(
                'SELECT updated_at FROM "broker"."broker_bucket" WHERE bucket_id = 1'
            )
        ).one()
        assert row[0] == created
    engine.dispose()

    recompare = conform.compare([BrokerBucket], allow_not_null_backfill=True)
    assert not isinstance(recompare, ConformError), str(recompare)
    assert len(recompare.steps) == 0
