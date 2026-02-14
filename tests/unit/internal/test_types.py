"""
Unit tests for neutral type constants and helpers.

Traceability: docs/technical/02-architecture.md (Core functions: Internal schema; Types).
"""

from modelsync.internal import (
    CanonicalType,
    canonical_char,
    canonical_numeric,
    canonical_varchar,
)


def test_canonical_type_enum() -> None:
    """CanonicalType StrEnum defines fixed canonical type names."""
    assert CanonicalType.INTEGER == "INTEGER"
    assert CanonicalType.BIGINT == "BIGINT"
    assert CanonicalType.TEXT == "TEXT"
    assert CanonicalType.TIMESTAMP == "TIMESTAMP"


def test_canonical_varchar() -> None:
    """canonical_varchar returns neutral VARCHAR(n) type string."""
    assert canonical_varchar(255) == "VARCHAR(255)"
    assert canonical_varchar(1) == "VARCHAR(1)"


def test_canonical_char() -> None:
    """canonical_char returns neutral CHAR(n) type string."""
    assert canonical_char(10) == "CHAR(10)"


def test_canonical_numeric() -> None:
    """canonical_numeric returns neutral NUMERIC type string."""
    assert canonical_numeric(10, 2) == "NUMERIC(10,2)"
    assert canonical_numeric(10, None) == "NUMERIC(10)"
    assert canonical_numeric(None, None) == "NUMERIC"
