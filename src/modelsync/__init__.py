"""
modelsync — schema and model synchronization.

Document-driven project; requirements live under docs/requirements/.
Library API: ModelSync(connection=... | credentials=..., target_schema=...),
sync.compare(models) -> SyncPlan | SyncError.
"""

__version__ = "0.1.0"

from modelsync.errors import SyncError
from modelsync.plan.steps import SyncPlan
from modelsync.sync import ModelSync

__all__ = [
    "ModelSync",
    "SyncError",
    "SyncPlan",
]
