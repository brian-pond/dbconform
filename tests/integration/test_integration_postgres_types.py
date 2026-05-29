"""
Integration tests: PostgreSQL-specific neutral type mapping.

Traceability: docs/requirements/01-functional.md (Schema parity, Backends).
GitHub #3 (DDL emits BYTEA), #7 (reflected BYTEA normalizes to BLOB),
#4 (JSONB), #5 (TIMESTAMPTZ).
"""

from datetime import datetime

from sqlalchemy import DateTime, create_engine, text
from sqlalchemy.dialects.postgresql import BYTEA, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

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
