"""
Unit tests for SQLAlchemy Index → IndexDef extraction.

Traceability: docs/requirements/01-functional.md (Schema parity — indexes); GitHub #6.
"""

from sqlalchemy import Column, Index, Integer, MetaData, String, Table, text

from dbconform.adapters.model_schema import ModelSchema, _index_to_def
from dbconform.sql_dialect.postgresql import PostgreSQLDialect


def test_index_to_def_partial_with_desc_and_where() -> None:
    """Partial index with text('priority DESC') and postgresql_where is preserved."""
    metadata = MetaData()
    table = Table(
        "broker_message",
        metadata,
        Column("queue_name", String),
        Column("state", String),
        Column("priority", Integer),
        Column("visible_at", String),
    )
    idx = Index(
        "broker_message_reserve_idx",
        "queue_name",
        "state",
        text("priority DESC"),
        "visible_at",
        postgresql_where=text("state = 'queued'"),
    )
    index_def = _index_to_def(idx, table)
    assert index_def.name == "broker_message_reserve_idx"
    assert index_def.column_exprs == (
        "queue_name",
        "state",
        "priority DESC",
        "visible_at",
    )
    assert index_def.where == "state = 'queued'"


def test_create_index_sql_partial_postgresql() -> None:
    """PostgreSQL CREATE INDEX includes DESC columns and WHERE clause."""
    from dbconform.internal.objects import IndexDef, QualifiedName

    dialect = PostgreSQLDialect()
    index = IndexDef(
        name="broker_message_reserve_idx",
        column_names=("queue_name", "state", "visible_at"),
        column_exprs=("queue_name", "state", "priority DESC", "visible_at"),
        where="state = 'queued'",
    )
    sql = dialect.create_index_sql(index, QualifiedName("broker", "broker_message"))
    assert '"priority" DESC' in sql
    assert "WHERE state = 'queued'" in sql
    assert '"broker"."broker_message"' in sql


def test_model_schema_extracts_partial_index() -> None:
    """ModelSchema.from_models preserves partial index via table.indexes."""
    from sqlalchemy.orm import DeclarativeBase

    class Base(DeclarativeBase):
        pass

    class BrokerMessage(Base):
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

    schema = ModelSchema.from_models(BrokerMessage)
    table_def = next(iter(schema.tables.values()))
    assert len(table_def.indexes) == 1
    idx = table_def.indexes[0]
    assert idx.column_exprs == ("queue_name", "state", "priority DESC", "visible_at")
    assert idx.where == "state = 'queued'"
