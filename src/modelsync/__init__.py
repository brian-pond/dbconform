"""
modelsync — schema and model synchronization.

Document-driven project; requirements live under docs/requirements/.
Library API: ModelSync(connection=... | credentials=..., target_schema=...),
sync.compare(models) -> SyncPlan | SyncError.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("modelsync")
except PackageNotFoundError:
    __version__ = "0.0.0"

from modelsync.errors import SyncError
from modelsync.plan.steps import SyncPlan
from modelsync.sync import ModelSync

__all__ = [
    "ModelSync",
    "SyncError",
    "SyncPlan",
]
