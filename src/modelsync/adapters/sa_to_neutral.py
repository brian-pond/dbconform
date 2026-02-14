"""
Map SQLAlchemy column types to neutral type names (no dialect).

Used when building internal schema from code models so that model-side schema
does not depend on a target database. See docs/technical/02-architecture.md
(Types, Internal schema: design goals) and the plan (Option B: neutral type vocabulary).
"""

from __future__ import annotations

import re
from typing import Any

from modelsync.internal.types import (
    CanonicalType,
    canonical_char,
    canonical_numeric,
    canonical_varchar,
)


def sa_column_to_neutral_type(column: Any) -> str:
    """
    Return the neutral data_type_name for a SQLAlchemy column (no dialect).

    Maps common SQLAlchemy types to the neutral vocabulary (INTEGER, VARCHAR(n),
    TEXT, FLOAT, BOOLEAN, DATE, TIMESTAMP, NUMERIC(p,s), etc.). Used when building
    ModelSchema from models so that no target database is assumed.
    """
    typ = column.type
    type_cls = type(typ)
    name = type_cls.__name__

    if name in ("Integer", "INTEGER"):
        return CanonicalType.INTEGER
    if name in ("BigInteger", "BIGINT"):
        return CanonicalType.BIGINT
    if name in ("SmallInteger", "SMALLINT"):
        return CanonicalType.SMALLINT
    if name in ("Float", "FLOAT", "REAL"):
        return CanonicalType.FLOAT
    if name in ("Boolean", "BOOLEAN", "Bool"):
        return CanonicalType.BOOLEAN
    if name in ("Text", "TEXT", "CLOB"):
        return CanonicalType.TEXT
    if name in ("Date", "DATE", "Date"):
        return CanonicalType.DATE
    if name in ("DateTime", "DATETIME", "TIMESTAMP", "DateTime", "Timestamp"):
        return CanonicalType.TIMESTAMP
    if name in ("Numeric", "NUMERIC", "Decimal", "DECIMAL"):
        precision = getattr(typ, "precision", None)
        scale = getattr(typ, "scale", None)
        return canonical_numeric(precision, scale)
    if name in ("String", "VARCHAR", "CHAR", "Unicode"):
        length = getattr(typ, "length", None)
        if length is not None:
            if name in ("CHAR", "Char"):
                return canonical_char(length)
            return canonical_varchar(length)
        return canonical_varchar(255)  # common default when no length
    if name in ("LargeBinary", "BLOB", "BYTEA"):
        return CanonicalType.BLOB
    if name in ("JSON", "JSONB"):
        return CanonicalType.JSON

    # Fallback: try compile with a generic dialect to get a string, then normalize
    # so we don't fail on custom or rare types. Use SQLite as a simple dialect.
    try:
        from sqlalchemy.dialects import sqlite
        compiled = typ.compile(dialect=sqlite.dialect())
        # Normalize common SQLite outputs to neutral
        c = str(compiled).strip().upper()
        if c == "INTEGER":
            return CanonicalType.INTEGER
        if c in ("REAL", "DOUBLE", "DOUBLE PRECISION"):
            return CanonicalType.FLOAT
        if c == "TEXT":
            return CanonicalType.TEXT
        if c == "BLOB":
            return CanonicalType.BLOB
        if c == "BOOLEAN":
            return CanonicalType.BOOLEAN
        if "VARCHAR" in c or "CHAR" in c:
            m = re.search(r"(\d+)", c)
            if m:
                return canonical_varchar(int(m.group(1)))
            return canonical_varchar(255)
        return str(compiled)
    except Exception:
        return CanonicalType.TEXT  # safe fallback
