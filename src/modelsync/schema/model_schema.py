"""Re-export model schema builder. Canonical: modelsync.adapters.model_schema."""

from modelsync.adapters.model_schema import ModelSchema, _extract_table_def

__all__ = [
    "ModelSchema",
    "_extract_table_def",
]
