"""
Map SQLAlchemy column types to neutral type names for model ingestion.

Used when building internal schema from code models (not database reflection).
Maps known SQLAlchemy types by class name; resolves ``TypeDecorator`` via
``load_dialect_impl(model_type_dialect)`` when the conform target dialect is
known (GitHub #10), or via ``impl`` when it is not. Does not compile
dialect-specific types (e.g. ``postgresql.BYTEA``) with the target compiler—
those are mapped by name so models remain portable across backends.

See docs/technical/02-architecture.md (Types: model ingestion vs reflection).
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from dbconform.internal.types import (
    CanonicalType,
    canonical_char,
    canonical_numeric,
    canonical_varchar,
)


def sa_column_to_neutral_type(
    column: Any,
    model_type_dialect: Dialect | None = None,
) -> str:
    """
    Return the neutral data_type_name for a SQLAlchemy column (model ingestion path).

    Maps common SQLAlchemy types to the neutral vocabulary (INTEGER, VARCHAR(n),
    TEXT, etc.). When ``model_type_dialect`` is provided,
    :class:`~sqlalchemy.types.TypeDecorator` subclasses are resolved via
    :meth:`~sqlalchemy.types.TypeDecorator.load_dialect_impl`. When it is None,
    ``TypeDecorator`` falls back to its ``impl`` attribute.
    """
    return sa_type_to_neutral_type(column.type, model_type_dialect=model_type_dialect)


def sa_type_to_neutral_type(
    typ: Any,
    model_type_dialect: Dialect | None = None,
) -> str:
    """
    Return the neutral data_type_name for a SQLAlchemy type object (model ingestion path).

    See :func:`sa_column_to_neutral_type`.
    """
    if isinstance(typ, TypeDecorator):
        resolved = (
            typ.load_dialect_impl(model_type_dialect)
            if model_type_dialect is not None
            else typ.impl
        )
        return sa_type_to_neutral_type(resolved, model_type_dialect=model_type_dialect)

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
    if name in ("DateTime", "DATETIME", "TIMESTAMP", "Timestamp"):
        if getattr(typ, "timezone", False):
            return CanonicalType.TIMESTAMPTZ
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
    if name == "JSONB":
        return CanonicalType.JSONB
    if name == "JSON":
        return CanonicalType.JSON

    # Last resort for unknown types: compile (never used for known dialect-specific types).
    try:
        from sqlalchemy.dialects import sqlite

        compile_dialect = model_type_dialect if model_type_dialect is not None else sqlite.dialect()
        compiled = typ.compile(dialect=compile_dialect)
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
