"""
Canonical type strings for schema comparison and DDL mapping.

ColumnDef.type_expr uses these canonical forms so that model and reflected
schema compare equal across backends. Dialects map platform-specific type
strings to canonical (to_canonical_type_expr) and canonical to DDL (to_ddl_type).
See docs/technical/02-architecture.md (Types).
"""

from __future__ import annotations

# Canonical type string constants for integer and float.
# VARCHAR and CHAR use parameterized form VARCHAR(n) / CHAR(n).
CANONICAL_INTEGER = "INTEGER"
CANONICAL_BIGINT = "BIGINT"
CANONICAL_FLOAT = "FLOAT"


def canonical_varchar(length: int) -> str:
    """Return canonical type string for a variable-length string column."""
    return f"VARCHAR({length})"


def canonical_char(length: int) -> str:
    """Return canonical type string for a fixed-length char column."""
    return f"CHAR({length})"
