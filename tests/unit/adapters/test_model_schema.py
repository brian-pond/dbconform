"""
Unit tests for ModelSchema and ingestion.

Traceability: docs/technical/02-architecture.md (Adapters, read-only contract);
docs/technical/05-model-column-defaults.md (Python scalar defaults → DDL);
docs/requirements/01-functional.md (Model discovery and API).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Integer
from sqlmodel import Field, SQLModel


class _SQLModelDateDefaultRow(SQLModel, table=True):
    """
    Module-level SQLModel so annotations like ``date`` resolve (see SQLModel + ForwardRef).

    Traceability: docs/technical/05-model-column-defaults.md.
    """

    __tablename__ = "sqlmodel_date_default_ingest"

    id: int | None = Field(default=None, primary_key=True)
    effective_from: date = Field(default=date(1970, 1, 1))


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


def test_python_date_default_emits_quoted_sql_literal() -> None:
    """
    Bare str(date) in DDL breaks PostgreSQL (parses as 1970 - 1 - 1).

    Regression: docs/technical/05-model-column-defaults.md.
    """
    from sqlalchemy import Column, Date
    from sqlalchemy.orm import DeclarativeBase

    from dbconform.adapters.model_schema import ModelSchema

    class Base(DeclarativeBase):
        pass

    class Row(Base):
        __tablename__ = "row_date_default"
        id = Column(Integer, primary_key=True)
        effective_from = Column(Date, nullable=False, default=date(1970, 1, 1))

    schema = ModelSchema.from_models(Row)
    table_def = next(iter(schema.tables.values()))
    col = table_def.column_by_name()["effective_from"]
    assert col.default == "'1970-01-01'"


def test_sqlmodel_field_date_default_emits_quoted_literal() -> None:
    """SQLModel Field(default=date(...)) uses Python-side default; same quoting rule applies."""
    from dbconform.adapters.model_schema import ModelSchema

    schema = ModelSchema.from_models(_SQLModelDateDefaultRow)
    table_def = next(iter(schema.tables.values()))
    assert table_def.column_by_name()["effective_from"].default == "'1970-01-01'"


def test_python_scalar_defaults_string_bool_datetime() -> None:
    """Strings (with escape), bool, and datetime map to SQL literal fragments."""
    from datetime import datetime

    from sqlalchemy import Boolean, Column, DateTime, String, Text
    from sqlalchemy.orm import DeclarativeBase

    from dbconform.adapters.model_schema import ModelSchema

    class Base(DeclarativeBase):
        pass

    class Row(Base):
        __tablename__ = "row_mixed_defaults"
        id = Column(Integer, primary_key=True)
        label = Column(String(50), default="O'Brien")
        active = Column(Boolean, default=True)
        created = Column(DateTime, default=datetime(2020, 1, 2, 3, 4, 5))
        body = Column(Text, default="x")

    schema = ModelSchema.from_models(Row)
    table_def = next(iter(schema.tables.values()))
    by = table_def.column_by_name()
    assert by["label"].default == "'O''Brien'"
    assert by["active"].default == "TRUE"
    assert by["created"].default == "'2020-01-02 03:04:05'"
    assert by["body"].default == "'x'"


def test_server_default_text_clause_unchanged_for_date_string() -> None:
    """ClauseElement .arg still uses str() so SQL quoting matches SQLAlchemy."""
    from sqlalchemy import Column, text
    from sqlalchemy.orm import DeclarativeBase

    from dbconform.adapters.model_schema import ModelSchema

    class Base(DeclarativeBase):
        pass

    class Row(Base):
        __tablename__ = "row_server_date"
        id = Column(Integer, primary_key=True)
        d = Column(Date, nullable=False, server_default=text("'1970-01-01'"))

    schema = ModelSchema.from_models(Row)
    assert next(iter(schema.tables.values())).column_by_name()["d"].default == "'1970-01-01'"


def test_python_scalar_to_sql_literal_rejects_unknown_and_nan() -> None:
    """Unserializable scalars must not become misleading str(value) DDL fragments."""
    import math

    from dbconform.adapters.model_schema import _python_scalar_to_sql_literal

    assert _python_scalar_to_sql_literal(object()) is None
    assert _python_scalar_to_sql_literal(float("nan")) is None
    assert _python_scalar_to_sql_literal(float("inf")) is None
    assert _python_scalar_to_sql_literal(b"bytes") is None
    assert _python_scalar_to_sql_literal(math.pi) == str(math.pi)


def test_implicit_autoincrement_single_integer_pk_is_true() -> None:
    """Single integer PK with SA implicit autoincrement maps to autoincrement=True."""
    from sqlalchemy import Column, Integer
    from sqlalchemy.orm import DeclarativeBase

    from dbconform.adapters.model_schema import ModelSchema

    class Base(DeclarativeBase):
        pass

    class Row(Base):
        __tablename__ = "row_implicit_pk_auto"
        id = Column(Integer, primary_key=True)

    schema = ModelSchema.from_models(Row)
    table_def = next(iter(schema.tables.values()))
    assert table_def.column_by_name()["id"].autoincrement is True


def test_implicit_autoincrement_disabled_when_pk_has_server_default() -> None:
    """autoincrement='auto' should be false when a default generator already exists."""
    from sqlalchemy import Column, Integer, text
    from sqlalchemy.orm import DeclarativeBase

    from dbconform.adapters.model_schema import ModelSchema

    class Base(DeclarativeBase):
        pass

    class Row(Base):
        __tablename__ = "row_pk_server_default"
        id = Column(Integer, primary_key=True, server_default=text("1"))

    schema = ModelSchema.from_models(Row)
    table_def = next(iter(schema.tables.values()))
    assert table_def.column_by_name()["id"].autoincrement is False


def test_implicit_autoincrement_false_for_non_integer_or_composite_pk() -> None:
    """Only single integer PK may map to implicit autoincrement."""
    from sqlalchemy import Column, String
    from sqlalchemy.orm import DeclarativeBase

    from dbconform.adapters.model_schema import ModelSchema

    class Base(DeclarativeBase):
        pass

    class NonIntegerPk(Base):
        __tablename__ = "non_integer_pk"
        id = Column(String(32), primary_key=True)

    class CompositePk(Base):
        __tablename__ = "composite_pk"
        a = Column(String(32), primary_key=True)
        b = Column(String(32), primary_key=True)

    non_integer_schema = ModelSchema.from_models(NonIntegerPk)
    non_integer_table = next(iter(non_integer_schema.tables.values()))
    assert non_integer_table.column_by_name()["id"].autoincrement is False

    composite_schema = ModelSchema.from_models(CompositePk)
    composite_table = next(iter(composite_schema.tables.values()))
    assert composite_table.column_by_name()["a"].autoincrement is False
    assert composite_table.column_by_name()["b"].autoincrement is False
