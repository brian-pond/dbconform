"""
Neutral type strings for schema comparison and DDL mapping.

ColumnDef.data_type_name uses these neutral forms so that model and reflected
schema compare equal across backends. Dialects map platform-specific type
strings to neutral (to_neutral_type) and neutral to DDL (to_ddl_type).
See docs/technical/02-architecture.md (Types).
"""

from __future__ import annotations

from enum import StrEnum


class CanonicalType(StrEnum):
    """
    All canonical type families (one member per type name we use).

    Unparameterized types (INTEGER, TEXT, DATE, …) use the enum value as
    data_type_name. Parameterized types use the helpers below, which build
    strings from these names: canonical_varchar(n) → "VARCHAR(n)",
    canonical_char(n) → "CHAR(n)", canonical_numeric(p,s) → "NUMERIC(p,s)"
    or CanonicalType.NUMERIC when omitted.
    """

    INTEGER = "INTEGER"
    BIGINT = "BIGINT"
    SMALLINT = "SMALLINT"
    FLOAT = "FLOAT"
    BOOLEAN = "BOOLEAN"
    TEXT = "TEXT"
    VARCHAR = "VARCHAR"
    CHAR = "CHAR"
    DATE = "DATE"
    TIMESTAMP = "TIMESTAMP"
    BLOB = "BLOB"
    JSON = "JSON"
    NUMERIC = "NUMERIC"


def canonical_varchar(length: int) -> str:
    """Return neutral type string for a variable-length string (VARCHAR(n))."""
    return f"{CanonicalType.VARCHAR}({length})"


def canonical_char(length: int) -> str:
    """Return neutral type string for a fixed-length string (CHAR(n))."""
    return f"{CanonicalType.CHAR}({length})"


def canonical_numeric(
    precision: int | None = None,
    scale: int | None = None,
) -> str:
    """Return neutral type string for NUMERIC; no args returns CanonicalType.NUMERIC."""
    if precision is not None and scale is not None:
        return f"NUMERIC({precision},{scale})"
    if precision is not None:
        return f"NUMERIC({precision})"
    return CanonicalType.NUMERIC
