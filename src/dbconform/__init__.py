"""
dbconform — conform database schema to models.

Document-driven project; requirements live under docs/requirements/.
Library API: DbConform (sync) or AsyncDbConform (async); connection/credentials, target_schema;
compare(models), apply_changes(models).
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("dbconform")
except PackageNotFoundError:
    __version__ = "0.0.0"

from dbconform.conform import AsyncDbConform, DbConform
from dbconform.errors import ConformError
from dbconform.plan.steps import ConformPlan, RebuildTableStep

__all__ = [
    "AsyncDbConform",
    "DbConform",
    "ConformError",
    "ConformPlan",
    "RebuildTableStep",
]
