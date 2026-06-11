"""Category and severity types for skipped conform steps."""

from __future__ import annotations

import enum

from dbconform.internal.objects import ColumnDef


class SkippedCategory(str, enum.Enum):
    """Why a planned step was not applied."""

    UNSPECIFIED = "unspecified"
    EXTRA_COLUMN = "extra_column"
    MISSING_COLUMN = "missing_column"
    EXTRA_CONSTRAINT = "extra_constraint"
    MISSING_CONSTRAINT = "missing_constraint"
    COLUMN_SHRINK = "column_shrink"


class SkippedSeverity(str, enum.Enum):
    """Whether remaining drift is likely benign or harmful to ORM traffic."""

    WARNING = "warning"
    ERROR = "error"


def extra_column_severity(column: ColumnDef) -> SkippedSeverity:
    """
    Classify a DB-only column that was not dropped.

    NOT NULL without DEFAULT can break INSERTs that omit the column; nullable or
    defaulted extras are usually benign.
    """
    if not column.nullable and column.default is None:
        return SkippedSeverity.ERROR
    return SkippedSeverity.WARNING
