"""
Unit tests for neutral type constants and helpers.

Traceability: docs/technical/02-architecture.md (Types).
"""

from modelsync.schema import types as schema_types


def test_canonical_type_enum() -> None:
    """CanonicalType StrEnum defines fixed canonical type names."""
    assert schema_types.CanonicalType.INTEGER == "INTEGER"
    assert schema_types.CanonicalType.BIGINT == "BIGINT"
    assert schema_types.CanonicalType.TEXT == "TEXT"
    assert schema_types.CanonicalType.TIMESTAMP == "TIMESTAMP"


def test_canonical_varchar() -> None:
    """canonical_varchar returns neutral VARCHAR(n) type string."""
    assert schema_types.canonical_varchar(255) == "VARCHAR(255)"
    assert schema_types.canonical_varchar(1) == "VARCHAR(1)"


def test_canonical_char() -> None:
    """canonical_char returns neutral CHAR(n) type string."""
    assert schema_types.canonical_char(10) == "CHAR(10)"


def test_canonical_numeric() -> None:
    """canonical_numeric returns neutral NUMERIC type string."""
    assert schema_types.canonical_numeric(10, 2) == "NUMERIC(10,2)"
    assert schema_types.canonical_numeric(10, None) == "NUMERIC(10)"
    assert schema_types.canonical_numeric(None, None) == "NUMERIC"
