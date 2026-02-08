"""
Unit tests for SyncPlanBuilder.

Traceability: docs/requirements/01-functional.md (Plan and DDL order,
Destructive changes, Opt-in flags). Extra tables from removed_tables;
no DROP by default; allow_drop_table/allow_drop_column/allow_shrink_column
control destructive steps.
"""

from collections import OrderedDict

from modelsync.dialect.sqlite import SQLiteDialect
from modelsync.plan.builder import SyncPlanBuilder
from modelsync.plan.steps import DropTableStep, SyncPlan
from modelsync.schema.diff import DiffResult, TableDiff
from modelsync.schema.objects import ColumnDef, IndexDef, QualifiedName, TableDef


def test_sync_plan_statements_and_sql() -> None:
    """SyncPlan.statements() returns step SQL list; .sql() returns concatenated SQL."""
    plan = SyncPlan(steps=[], extra_tables=[])
    assert plan.statements() == []
    assert plan.sql() == ""


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
    """Removed table (DB-only) -> extra_tables, no DROP step when allow_drop_table=False."""
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


def test_builder_removed_table_drop_when_allow_drop_table() -> None:
    """Removed table (DB-only) -> DROP TABLE step when allow_drop_table=True (01-functional: Opt-in flags)."""
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
    plan = SyncPlanBuilder(SQLiteDialect(), allow_drop_table=True).build(diff)
    assert len(plan.steps) == 1
    assert isinstance(plan.steps[0], DropTableStep)
    assert plan.steps[0].table_name.name == "orphan"
    assert "DROP TABLE" in (plan.steps[0].sql or "")
    assert "orphan" in (plan.steps[0].sql or "")


def test_builder_removed_column_drop_when_allow_drop_column() -> None:
    """Modified table with removed column -> DROP COLUMN step when allow_drop_column=True."""
    qualified = QualifiedName(None, "t")
    old_table = TableDef(
        name=qualified,
        columns=(
            ColumnDef("id", "INTEGER", nullable=False),
            ColumnDef("extra", "TEXT", nullable=True),
        ),
    )
    new_table = TableDef(
        name=qualified,
        columns=(ColumnDef("id", "INTEGER", nullable=False),),
    )
    diff = DiffResult(
        added_tables=OrderedDict(),
        removed_tables=OrderedDict(),
        modified_tables=OrderedDict([
            (qualified, TableDiff(
                old_table=old_table,
                new_table=new_table,
                removed_columns=(ColumnDef("extra", "TEXT", nullable=True),),
            )),
        ]),
    )
    plan = SyncPlanBuilder(SQLiteDialect(), allow_drop_column=True).build(diff)
    assert len(plan.steps) == 1
    assert "DROP COLUMN" in (plan.steps[0].sql or "")
    assert "extra" in (plan.steps[0].sql or "")


def test_builder_alter_shrink_skipped_without_allow_shrink_column() -> None:
    """When change would shrink column length, no ALTER step unless allow_shrink_column=True."""
    qualified = QualifiedName(None, "t")
    old_table = TableDef(
        name=qualified,
        columns=(
            ColumnDef("id", "INTEGER", nullable=False),
            ColumnDef("name", "VARCHAR(500)", nullable=False),
        ),
    )
    new_table = TableDef(
        name=qualified,
        columns=(
            ColumnDef("id", "INTEGER", nullable=False),
            ColumnDef("name", "VARCHAR(255)", nullable=False),
        ),
    )
    diff = DiffResult(
        added_tables=OrderedDict(),
        removed_tables=OrderedDict(),
        modified_tables=OrderedDict([
            (qualified, TableDiff(
                old_table=old_table,
                new_table=new_table,
                modified_columns=(
                    (ColumnDef("name", "VARCHAR(500)", nullable=False),
                     ColumnDef("name", "VARCHAR(255)", nullable=False)),
                ),
            )),
        ]),
    )
    # Dialect that would emit ALTER; would_shrink is True (SQLite for VARCHAR 500->255).
    # SQLite alter_column_sql returns None so we need a dialect that returns SQL to test skip.
    class ShrinkCapableDialect(SQLiteDialect):
        def alter_column_sql(self, _table_name, _old_column, _new_column):
            return 'ALTER TABLE "t" ALTER COLUMN "name" VARCHAR(255)'

    plan_no_shrink = SyncPlanBuilder(
        ShrinkCapableDialect(), allow_shrink_column=False
    ).build(diff)
    assert len(plan_no_shrink.steps) == 0

    plan_allow_shrink = SyncPlanBuilder(
        ShrinkCapableDialect(), allow_shrink_column=True
    ).build(diff)
    assert len(plan_allow_shrink.steps) == 1
    assert "ALTER COLUMN" in (plan_allow_shrink.steps[0].sql or "")


def test_sqlite_would_shrink_true_when_length_reduced() -> None:
    """SQLiteDialect.would_shrink returns True when new length < old length (VARCHAR/CHAR)."""
    dialect = SQLiteDialect()
    old_500 = ColumnDef("name", "VARCHAR(500)", nullable=False)
    new_255 = ColumnDef("name", "VARCHAR(255)", nullable=False)
    assert dialect.would_shrink(old_500, new_255) is True
    assert dialect.would_shrink(new_255, old_500) is False


def test_sqlite_would_shrink_false_when_same_length() -> None:
    """SQLiteDialect.would_shrink returns False when lengths are equal."""
    dialect = SQLiteDialect()
    col = ColumnDef("name", "VARCHAR(255)", nullable=False)
    assert dialect.would_shrink(col, col) is False


def test_builder_report_extra_tables_false() -> None:
    """When report_extra_tables=False, plan.extra_tables is empty despite removed_tables."""
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
    plan = SyncPlanBuilder(SQLiteDialect(), report_extra_tables=False).build(diff)
    assert len(plan.extra_tables) == 0


def test_builder_removed_index_drop_when_allow_drop_constraint_true() -> None:
    """Modified table with removed index -> DROP INDEX step when allow_drop_constraint=True (default) (01-functional: add/remove constraints)."""
    from modelsync.schema.diff import TableDiff

    qualified = QualifiedName(None, "t")
    old_table = TableDef(
        name=qualified,
        columns=(ColumnDef("id", "INTEGER", nullable=False),),
        indexes=(IndexDef("idx_t_id", ("id",), False),),
    )
    new_table = TableDef(
        name=qualified,
        columns=(ColumnDef("id", "INTEGER", nullable=False),),
        indexes=(),
    )
    diff = DiffResult(
        added_tables=OrderedDict(),
        removed_tables=OrderedDict(),
        modified_tables=OrderedDict([
            (qualified, TableDiff(
                old_table=old_table,
                new_table=new_table,
                removed_indexes=(IndexDef("idx_t_id", ("id",), False),),
            )),
        ]),
    )
    plan = SyncPlanBuilder(SQLiteDialect()).build(diff)  # default allow_drop_constraint=True
    assert len(plan.steps) == 1
    assert "DROP INDEX" in (plan.steps[0].sql or "")
    assert "idx_t_id" in (plan.steps[0].sql or "")


def test_builder_removed_index_no_drop_when_allow_drop_constraint_false() -> None:
    """Modified table with removed index -> no DROP step when allow_drop_constraint=False."""
    from modelsync.schema.diff import TableDiff

    qualified = QualifiedName(None, "t")
    old_table = TableDef(
        name=qualified,
        columns=(ColumnDef("id", "INTEGER", nullable=False),),
        indexes=(IndexDef("idx_t_id", ("id",), False),),
    )
    new_table = TableDef(
        name=qualified,
        columns=(ColumnDef("id", "INTEGER", nullable=False),),
        indexes=(),
    )
    diff = DiffResult(
        added_tables=OrderedDict(),
        removed_tables=OrderedDict(),
        modified_tables=OrderedDict([
            (qualified, TableDiff(
                old_table=old_table,
                new_table=new_table,
                removed_indexes=(IndexDef("idx_t_id", ("id",), False),),
            )),
        ]),
    )
    plan = SyncPlanBuilder(SQLiteDialect(), allow_drop_constraint=False).build(diff)
    assert len(plan.steps) == 0


def test_builder_fk_order_parent_before_child() -> None:
    """Two added tables with FK: parent created before child (topological order)."""
    from modelsync.schema.objects import ForeignKeyDef

    parent_name = QualifiedName(None, "parent")
    child_name = QualifiedName(None, "child")
    parent_table = TableDef(
        name=parent_name,
        columns=(ColumnDef("id", "INTEGER", nullable=False),),
    )
    child_table = TableDef(
        name=child_name,
        columns=(
            ColumnDef("id", "INTEGER", nullable=False),
            ColumnDef("parent_id", "INTEGER", nullable=False),
        ),
        foreign_keys=(ForeignKeyDef(
            name=None,
            column_names=("parent_id",),
            ref_table=parent_name,
            ref_column_names=("id",),
        ),),
    )
    diff = DiffResult(
        added_tables=OrderedDict([
            (child_name, child_table),
            (parent_name, parent_table),
        ]),
        removed_tables=OrderedDict(),
        modified_tables=OrderedDict(),
    )
    plan = SyncPlanBuilder(SQLiteDialect()).build(diff)
    assert len(plan.steps) == 2
    assert "parent" in (plan.steps[0].sql or "")
    assert "child" in (plan.steps[1].sql or "")
    assert len(plan.statements()) == 2
    assert "parent" in plan.sql() and "child" in plan.sql()
