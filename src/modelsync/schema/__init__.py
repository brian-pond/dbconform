"""
Canonical schema representation for model-to-database comparison.

See docs/requirements/01-functional.md (Schema parity scope) and
docs/technical/02-architecture.md.
"""

from modelsync.schema.db_schema import DatabaseSchema
from modelsync.schema.diff import DiffResult, SchemaDiffer
from modelsync.schema.model_schema import ModelSchema
from modelsync.schema.objects import (
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
    "UniqueDef",
]
