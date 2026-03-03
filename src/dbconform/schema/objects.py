"""Re-export internal schema objects. Canonical: dbconform.internal.objects."""

from dbconform.internal.objects import (
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
    "ForeignKeyDef",
    "IndexDef",
    "PrimaryKeyDef",
    "QualifiedName",
    "TableDef",
    "UniqueDef",
]
