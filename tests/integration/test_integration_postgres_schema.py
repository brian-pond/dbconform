"""
Integration tests: non-public PostgreSQL schema table detection on compare.

Traceability: docs/requirements/01-functional.md (Target schema); GitHub #8.
"""

import pytest
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase

import dbconform
from dbconform.plan import CreateTableStep


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
