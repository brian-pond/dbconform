"""
dbconform — conform database schema to models.

Document-driven project; requirements live under docs/requirements/.
Library API: DbConform(connection=... | credentials=..., target_schema=...),
compare(models) -> ConformPlan | ConformError, apply_changes(models) to apply.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("dbconform")
except PackageNotFoundError:
    __version__ = "0.0.0"

from dbconform.conform import DbConform
from dbconform.errors import ConformError
from dbconform.plan.steps import ConformPlan

__all__ = [
    "DbConform",
    "ConformError",
    "ConformPlan",
]
