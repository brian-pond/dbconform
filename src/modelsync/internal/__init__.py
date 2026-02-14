"""
Neutral internal schema: objects and type names.

No dependency on SQLAlchemy, Django, or other ORMs. See docs/technical/02-architecture.md
(Core functions, Internal schema).
"""

from modelsync.internal.objects import (
    CheckDef,
    ColumnDef,
    ForeignKeyDef,
    IndexDef,
    PrimaryKeyDef,
    QualifiedName,
    TableDef,
    UniqueDef,
)
from modelsync.internal.types import (
    CanonicalType,
    canonical_char,
    canonical_numeric,
    canonical_varchar,
)

__all__ = [
    "CanonicalType",
    "CheckDef",
    "ColumnDef",
    "ForeignKeyDef",
    "IndexDef",
    "PrimaryKeyDef",
    "QualifiedName",
    "TableDef",
    "UniqueDef",
    "canonical_char",
    "canonical_numeric",
    "canonical_varchar",
]
