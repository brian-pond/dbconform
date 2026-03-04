"""
Unit tests for ModelSchema and ingestion.

Traceability: docs/technical/02-architecture.md (Adapters, read-only contract);
docs/requirements/01-functional.md (Model discovery and API).
"""

from __future__ import annotations


def _table_fingerprint(table: object) -> tuple[object, ...]:
    """
    Return a hashable fingerprint of a SQLAlchemy Table for mutation checks.

    Uses only read-only attributes: name, schema, and per-column (name, type class name, nullable).
    """
    from sqlalchemy import Table

    if not isinstance(table, Table):
        raise TypeError(f"Expected Table, got {type(table)}")
    name = (getattr(table, "name", None), getattr(table, "schema", None))
    cols = []
    for c in table.c:
        type_cls = type(getattr(c, "type", None))
        cols.append((c.name, type_cls.__name__, c.nullable))
    return (name, tuple(cols))


def test_from_models_does_not_mutate_caller_models() -> None:
    """
    ModelSchema.from_models() does not mutate the caller's model or __table__.

    Regression test for read-only ingestion contract (02-architecture: Adapters).
    """
    from sqlalchemy import Column, Integer, String
    from sqlalchemy.orm import DeclarativeBase

    from dbconform.adapters.model_schema import ModelSchema

    class Base(DeclarativeBase):
        pass

    class LocalModel(Base):
        __tablename__ = "local_test_table"
        id = Column(Integer, primary_key=True, autoincrement=True)
        name = Column(String(255), nullable=False)

    table = LocalModel.__table__
    before = _table_fingerprint(table)
    ModelSchema.from_models(LocalModel)
    after = _table_fingerprint(table)
    assert after == before, "Ingestion must not mutate the caller's Table"


def test_from_models_sequence_does_not_mutate() -> None:
    """Same guarantee when passing a sequence of models."""
    from sqlalchemy import Column, Integer, String
    from sqlalchemy.orm import DeclarativeBase

    from dbconform.adapters.model_schema import ModelSchema

    class Base(DeclarativeBase):
        pass

    class A(Base):
        __tablename__ = "seq_a"
        id = Column(Integer, primary_key=True)
        x = Column(String(100), nullable=True)

    class B(Base):
        __tablename__ = "seq_b"
        id = Column(Integer, primary_key=True)
        y = Column(String(50), nullable=False)

    fp_a_before = _table_fingerprint(A.__table__)
    fp_b_before = _table_fingerprint(B.__table__)
    ModelSchema.from_models([A, B])
    assert _table_fingerprint(A.__table__) == fp_a_before
    assert _table_fingerprint(B.__table__) == fp_b_before


def test_check_constraint_in_clause_expands_to_literals() -> None:
    """
    CHECK constraints with IN(enum_values) must expand to literals, not POSTCOMPILE placeholders.

    SQLAlchemy emits __[POSTCOMPILE_param_1] for IN(); raw DDL execution would fail.
    """
    from sqlalchemy import CheckConstraint, Column, Integer, String
    from sqlalchemy.orm import DeclarativeBase
    from sqlalchemy.sql import column

    from dbconform.adapters.model_schema import ModelSchema

    class Base(DeclarativeBase):
        pass

    class TableWithEnumCheck(Base):
        __tablename__ = "execution_lanes"
        id = Column(Integer, primary_key=True)
        concurrency_mode = Column(String(50), nullable=False)
        priority = Column(String(50), nullable=False)
        __table_args__ = (
            CheckConstraint(
                column("concurrency_mode").in_(["sequential", "parallel"]),
                name="concurrencymode",
            ),
            CheckConstraint(
                column("priority").in_(["high", "low", "normal"]),
                name="lanepriority",
            ),
        )

    schema = ModelSchema.from_models(TableWithEnumCheck)
    table_def = next(iter(schema.tables.values()))
    for ck in table_def.check_constraints:
        assert "__[POSTCOMPILE" not in ck.expression, f"Placeholder in {ck.name}: {ck.expression}"
        assert "IN (" in ck.expression
        # Values should be literal strings
        assert "'sequential'" in ck.expression or "'high'" in ck.expression or "'parallel'" in ck.expression
