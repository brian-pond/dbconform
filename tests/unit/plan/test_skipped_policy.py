"""Unit tests for skipped-step severity and plan finalization."""

from io import StringIO

import pytest

from dbconform.errors import ConformError
from dbconform.internal.objects import ColumnDef, QualifiedName
from dbconform.plan.skipped_policy import finalize_plan_drift, make_skipped_step
from dbconform.plan.skipped_types import SkippedCategory, SkippedSeverity, extra_column_severity
from dbconform.plan.steps import ConformPlan


def test_extra_column_severity_nullable_is_warning() -> None:
    """Extra nullable DB column is benign drift."""
    col = ColumnDef("legacy", "VARCHAR(32)", nullable=True)
    assert extra_column_severity(col) == SkippedSeverity.WARNING


def test_extra_column_severity_not_null_no_default_is_error() -> None:
    """Extra NOT NULL column without default can break ORM INSERTs."""
    col = ColumnDef("legacy", "VARCHAR(32)", nullable=False)
    assert extra_column_severity(col) == SkippedSeverity.ERROR


def test_extra_column_severity_not_null_with_default_is_warning() -> None:
    """Extra NOT NULL column with DEFAULT is usually benign."""
    col = ColumnDef("legacy", "VARCHAR(32)", nullable=False, default="'x'")
    assert extra_column_severity(col) == SkippedSeverity.WARNING


def test_finalize_plan_drift_warning_only_returns_none(capsys: pytest.CaptureFixture[str]) -> None:
    """Warning-severity skips emit stderr but do not fail."""
    plan = ConformPlan(
        skipped_steps=[
            make_skipped_step(
                description="Drop column `extra` from `t`",
                reason="allow_drop_extra_columns=False",
                table_name=QualifiedName(None, "t"),
                category=SkippedCategory.EXTRA_COLUMN,
                severity=SkippedSeverity.WARNING,
            )
        ],
    )
    err = finalize_plan_drift(plan, emit_log=False)
    assert err is None
    assert "skipped step [warning]" in capsys.readouterr().err


def test_finalize_plan_drift_error_returns_conform_error(capsys: pytest.CaptureFixture[str]) -> None:
    """Error-severity skips return ConformError."""
    plan = ConformPlan(
        skipped_steps=[
            make_skipped_step(
                description="Add column updated_at to t",
                reason="allow_not_null_backfill=False",
                table_name=QualifiedName(None, "t"),
                category=SkippedCategory.MISSING_COLUMN,
                severity=SkippedSeverity.ERROR,
            )
        ],
    )
    err = finalize_plan_drift(plan, emit_log=False)
    assert isinstance(err, ConformError)
    assert err.plan is plan
    assert "allow_not_null_backfill" in str(err)
    assert "skipped step [error]" in capsys.readouterr().err


def test_finalize_plan_drift_extra_tables_warn_only(capsys: pytest.CaptureFixture[str]) -> None:
    """Extra tables emit warning but do not fail."""
    plan = ConformPlan(extra_tables=[QualifiedName("public", "orphan")])
    err = finalize_plan_drift(plan, emit_log=False)
    assert err is None
    assert "extra table" in capsys.readouterr().err.lower()
