"""
Adapters: third-party models (SQLAlchemy, SQLModel) → internal schema.

See docs/technical/02-architecture.md (Core functions, Adapters).
"""

from dbconform.adapters.model_schema import ModelSchema
from dbconform.adapters.sa_to_neutral import sa_column_to_neutral_type

__all__ = [
    "ModelSchema",
    "sa_column_to_neutral_type",
]
