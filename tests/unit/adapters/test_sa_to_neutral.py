"""
Unit tests for SQLAlchemy column to neutral type mapping.

Traceability: docs/technical/02-architecture.md (Core functions: Adapters ingest; Types).
"""

from sqlalchemy import Column
from sqlalchemy import types as sa_types

from dbconform.adapters import sa_column_to_neutral_type


def test_sa_column_integer() -> None:
    """Integer maps to INTEGER."""
    col = Column("id", sa_types.Integer())
    assert sa_column_to_neutral_type(col) == "INTEGER"


def test_sa_column_biginteger() -> None:
    """BigInteger maps to BIGINT."""
    col = Column("id", sa_types.BigInteger())
    assert sa_column_to_neutral_type(col) == "BIGINT"


def test_sa_column_string_with_length() -> None:
    """String(255) maps to VARCHAR(255)."""
    col = Column("name", sa_types.String(255))
    assert sa_column_to_neutral_type(col) == "VARCHAR(255)"


def test_sa_column_string_no_length() -> None:
    """String() maps to VARCHAR(255) default."""
    col = Column("name", sa_types.String())
    assert sa_column_to_neutral_type(col) == "VARCHAR(255)"


def test_sa_column_float() -> None:
    """Float maps to FLOAT."""
    col = Column("value", sa_types.Float())
    assert sa_column_to_neutral_type(col) == "FLOAT"


def test_sa_column_text() -> None:
    """Text maps to TEXT."""
    col = Column("body", sa_types.Text())
    assert sa_column_to_neutral_type(col) == "TEXT"


def test_sa_column_boolean() -> None:
    """Boolean maps to BOOLEAN."""
    col = Column("flag", sa_types.Boolean())
    assert sa_column_to_neutral_type(col) == "BOOLEAN"
