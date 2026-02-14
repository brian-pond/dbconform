"""Re-export compare diff. Canonical: modelsync.compare.diff."""

from modelsync.compare.diff import DiffResult, SchemaDiffer, TableDiff, differences

__all__ = [
    "DiffResult",
    "SchemaDiffer",
    "TableDiff",
    "differences",
]
