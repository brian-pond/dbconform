"""Re-export compare diff. Canonical: dbconform.compare.diff."""

from dbconform.compare.diff import DiffResult, SchemaDiffer, TableDiff, differences

__all__ = [
    "DiffResult",
    "SchemaDiffer",
    "TableDiff",
    "differences",
]
