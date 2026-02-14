"""
Public schema API; re-exports from modelsync.internal, modelsync.adapters, modelsync.compare.

See docs/technical/02-architecture.md (Package layout).
"""

from modelsync.compare import DatabaseSchema, DiffResult, SchemaDiffer, TableDiff, differences
from modelsync.adapters import ModelSchema, sa_column_to_neutral_type
from modelsync.internal import (
    CheckDef,
    ColumnDef,
    ForeignKeyDef,
    IndexDef,
    PrimaryKeyDef,
    QualifiedName,
    TableDef,
    UniqueDef,
)

__all__ = [
    "CheckDef",
    "ColumnDef",
    "DatabaseSchema",
    "DiffResult",
    "ForeignKeyDef",
    "IndexDef",
    "ModelSchema",
    "PrimaryKeyDef",
    "QualifiedName",
    "SchemaDiffer",
    "TableDef",
    "TableDiff",
    "UniqueDef",
    "differences",
    "sa_column_to_neutral_type",
]
