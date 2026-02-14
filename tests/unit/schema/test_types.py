"""
Unit tests for canonical type constants and helpers.

Traceability: docs/technical/02-architecture.md (Types).
"""

from modelsync.schema import types as schema_types


def test_canonical_constants() -> None:
    """Canonical type string constants are defined."""
    assert schema_types.CANONICAL_INTEGER == "INTEGER"
    assert schema_types.CANONICAL_BIGINT == "BIGINT"
    assert schema_types.CANONICAL_FLOAT == "FLOAT"


def test_canonical_varchar() -> None:
    """canonical_varchar returns VARCHAR(n)."""
    assert schema_types.canonical_varchar(255) == "VARCHAR(255)"
    assert schema_types.canonical_varchar(1) == "VARCHAR(1)"


def test_canonical_char() -> None:
    """canonical_char returns CHAR(n)."""
    assert schema_types.canonical_char(10) == "CHAR(10)"
