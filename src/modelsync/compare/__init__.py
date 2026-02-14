"""
Compare: reflect DB into database-side internal schema and diff against model-side internal schema.

See docs/technical/02-architecture.md (Core functions, Compare).
"""

from modelsync.compare.db_schema import DatabaseSchema
from modelsync.compare.diff import DiffResult, SchemaDiffer, TableDiff, differences

__all__ = [
    "DatabaseSchema",
    "DiffResult",
    "SchemaDiffer",
    "TableDiff",
    "differences",
]
