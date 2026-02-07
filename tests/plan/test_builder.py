"""
Unit tests for SyncPlanBuilder.

Traceability: docs/requirements/01-functional.md (Plan and DDL order,
Destructive changes). Extra tables from removed_tables; no DROP by default.
"""

from collections import OrderedDict

from modelsync.dialect.sqlite import SQLiteDialect
from modelsync.plan.builder import SyncPlanBuilder
from modelsync.schema.diff import DiffResult
from modelsync.schema.objects import ColumnDef, QualifiedName, TableDef


def test_builder_added_table_produces_create_step() -> None:
    """One added table -> one CreateTable step."""
    diff = DiffResult(
        added_tables=OrderedDict([
            (QualifiedName(None, "foo"), TableDef(
                name=QualifiedName(None, "foo"),
                columns=(ColumnDef("id", "INTEGER", nullable=False),),
            )),
        ]),
        removed_tables=OrderedDict(),
        modified_tables=OrderedDict(),
    )
    plan = SyncPlanBuilder(SQLiteDialect()).build(diff)
    assert len(plan.steps) == 1
    assert "CREATE TABLE" in (plan.steps[0].sql or "")
    assert "foo" in (plan.steps[0].sql or "")


def test_builder_removed_table_in_extra_no_drop() -> None:
    """Removed table (DB-only) -> extra_tables, no DROP step."""
    diff = DiffResult(
        added_tables=OrderedDict(),
        removed_tables=OrderedDict([
            (QualifiedName(None, "orphan"), TableDef(
                name=QualifiedName(None, "orphan"),
                columns=(ColumnDef("id", "INTEGER", nullable=False),),
            )),
        ]),
        modified_tables=OrderedDict(),
    )
    plan = SyncPlanBuilder(SQLiteDialect(), report_extra_tables=True).build(diff)
    assert len(plan.steps) == 0
    assert len(plan.extra_tables) == 1
    assert plan.extra_tables[0].name == "orphan"
