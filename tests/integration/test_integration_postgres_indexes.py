"""
Integration tests: PostgreSQL partial indexes with sort order and WHERE.

Traceability: docs/requirements/01-functional.md (Schema parity — indexes); GitHub #6.
"""

from sqlalchemy import Column, Index, Integer, String, create_engine, text
from sqlalchemy.orm import DeclarativeBase

import dbconform
from dbconform.plan import CreateIndexStep, CreateTableStep


class _Base(DeclarativeBase):
    """Declarative base for partial index integration tests."""


class BrokerMessage(_Base):
    """Model with partial index matching Better Broker reserve index."""

    __tablename__ = "broker_message"

    queue_name = Column(String, primary_key=True)
    state = Column(String, nullable=False)
    priority = Column(Integer, nullable=False)
    visible_at = Column(String, nullable=False)

    __table_args__ = (
        Index(
            "broker_message_reserve_idx",
            "queue_name",
            "state",
            text("priority DESC"),
            "visible_at",
            postgresql_where=text("state = 'queued'"),
        ),
    )


def _pg_index_def(url: str, schema: str, index_name: str) -> tuple[str, str | None]:
    """Return (indexdef, predicate) from pg_indexes for the given index."""
    engine = create_engine(url)
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = :schema AND indexname = :name"
            ),
            {"schema": schema, "name": index_name},
        ).one()
        pred_row = conn.execute(
            text(
                "SELECT pg_get_expr(indpred, indrelid) FROM pg_index "
                "JOIN pg_class ON pg_class.oid = pg_index.indexrelid "
                "WHERE pg_class.relname = :name"
            ),
            {"name": index_name},
        ).one()
    engine.dispose()
    return row[0], pred_row[0]


def test_apply_partial_index_postgres(empty_postgres_db: tuple[str, str]) -> None:
    """Apply creates partial index with DESC and WHERE; re-compare is stable."""
    url, schema = empty_postgres_db
    conform = dbconform.DbConform(credentials={"url": url}, target_schema=schema)
    plan = conform.compare([BrokerMessage])
    assert not isinstance(plan, dbconform.ConformError)
    assert any(isinstance(s, CreateTableStep) for s in plan.steps)
    assert any(isinstance(s, CreateIndexStep) for s in plan.steps)

    result = conform.apply_changes([BrokerMessage], emit_log=False)
    assert not isinstance(result, dbconform.ConformError)

    indexdef, predicate = _pg_index_def(url, schema, "broker_message_reserve_idx")
    assert "priority DESC" in indexdef
    assert predicate is not None
    assert "queued" in predicate

    recompare = conform.compare([BrokerMessage])
    assert not isinstance(recompare, dbconform.ConformError)
    assert len(recompare.steps) == 0
