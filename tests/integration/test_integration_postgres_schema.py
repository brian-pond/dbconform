"""
Integration tests: non-public PostgreSQL schema table detection on compare.

Traceability: docs/requirements/01-functional.md (Target schema); GitHub #8, #9.
"""

import pytest
from sqlalchemy import Column, Enum, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase

import dbconform
from dbconform.plan import AlterTableStep, CreateTableStep


class _Base(DeclarativeBase):
    """Declarative base for schema-qualified integration tests."""


class BrokerQueue(_Base):
    """Table in non-public ``broker`` schema."""

    __tablename__ = "broker_queue"
    __table_args__ = {"schema": "broker"}

    queue_name = Column(String, primary_key=True)
    depth = Column(Integer, nullable=False, default=0)


def test_compare_detects_existing_broker_schema_table(
    postgres_broker_schema_db: tuple[str, str],
) -> None:
    """After create_all in broker schema, compare must not plan CREATE TABLE (GitHub #8)."""
    url, schema = postgres_broker_schema_db
    engine = create_engine(url)
    BrokerQueue.__table__.create(engine)
    engine.dispose()

    conform = dbconform.DbConform(credentials={"url": url}, target_schema=schema)
    plan = conform.compare([BrokerQueue])
    assert not isinstance(plan, dbconform.ConformError)
    create_steps = [s for s in plan.steps if isinstance(s, CreateTableStep)]
    assert create_steps == [], f"Unexpected create-table steps: {create_steps}"


@pytest.mark.asyncio
async def test_async_compare_detects_existing_broker_schema_table(
    postgres_broker_schema_db: tuple[str, str],
) -> None:
    """AsyncDbConform compare against non-public schema tables (GitHub #8)."""
    url, schema = postgres_broker_schema_db
    engine = create_engine(url)
    BrokerQueue.__table__.create(engine)
    engine.dispose()

    async_url = url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    conform = dbconform.AsyncDbConform(credentials={"url": async_url}, target_schema=schema)
    plan = await conform.compare([BrokerQueue])
    assert not isinstance(plan, dbconform.ConformError)
    create_steps = [s for s in plan.steps if isinstance(s, CreateTableStep)]
    assert create_steps == [], f"Unexpected create-table steps: {create_steps}"


class _EnumCheckBase(DeclarativeBase):
    """Declarative base for Enum CHECK constraint round-trip tests (GitHub #9)."""


class NotificationOutbox(_EnumCheckBase):
    """SQLAlchemy non-native enum with named CHECK constraint."""

    __tablename__ = "notification_outbox"
    __table_args__ = {"schema": "public"}

    id = Column(String(36), primary_key=True)
    status = Column(
        Enum(
            "pending",
            "sent",
            "failed",
            name="outboxstatus",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=False,
    )


def test_compare_enum_check_constraint_no_drift_on_recompare(
    empty_postgres_db: tuple[str, str],
) -> None:
    """Second compare against unchanged Enum CHECK must emit zero check steps (GitHub #9)."""
    url, schema = empty_postgres_db
    engine = create_engine(url)
    NotificationOutbox.__table__.create(engine)
    engine.dispose()

    conform = dbconform.DbConform(credentials={"url": url}, target_schema=schema)
    plan = conform.compare([NotificationOutbox])
    assert not isinstance(plan, dbconform.ConformError)
    check_steps = [
        s
        for s in plan.steps
        if isinstance(s, AlterTableStep) and "check constraint" in s.description.lower()
    ]
    assert check_steps == [], f"Unexpected check constraint steps: {check_steps}"


@pytest.mark.asyncio
async def test_async_apply_enum_check_with_allow_drop_extra_constraints_false(
    empty_postgres_db: tuple[str, str],
) -> None:
    """Re-apply with drops disabled must not raise DuplicateObjectError (GitHub #9)."""
    url, schema = empty_postgres_db
    engine = create_engine(url)
    NotificationOutbox.__table__.create(engine)
    engine.dispose()

    async_url = url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    conform = dbconform.AsyncDbConform(credentials={"url": async_url}, target_schema=schema)
    result = await conform.apply_changes(
        [NotificationOutbox],
        allow_drop_extra_constraints=False,
    )
    assert not isinstance(result, dbconform.ConformError), str(result)
    check_steps = [
        s
        for s in result.steps
        if isinstance(s, AlterTableStep) and "check constraint" in s.description.lower()
    ]
    assert check_steps == [], f"Unexpected check constraint steps: {check_steps}"
