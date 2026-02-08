"""
Build an ordered SyncPlan from a DiffResult and dialect.

Respects dependency order (create referenced tables before tables with FKs)
and options (no drops by default; extra tables reported only).
See docs/requirements/01-functional.md (Plan and DDL order, Destructive changes).
"""

from __future__ import annotations

from collections import deque

from modelsync.dialect.base import Dialect
from modelsync.plan.steps import (
    AlterTableStep,
    CreateIndexStep,
    CreateTableStep,
    DropTableStep,
    SyncPlan,
    SyncStep,
)
from modelsync.schema.diff import DiffResult
from modelsync.schema.objects import QualifiedName, TableDef


def _topological_table_order(
    tables: dict[QualifiedName, TableDef],
) -> list[QualifiedName]:
    """
    Return table names in an order such that referenced tables come first.

    If table A has FK to table B, we create B before A.
    """
    names = list(tables.keys())
    name_set = set(names)
    out_edges: dict[QualifiedName, list[QualifiedName]] = {n: [] for n in names}
    for n in names:
        t = tables[n]
        for fk in t.foreign_keys:
            ref = fk.ref_table
            if ref in name_set and ref != n:
                out_edges[ref].append(n)
    in_degree = dict.fromkeys(names, 0)
    for n in names:
        for m in out_edges[n]:
            in_degree[m] += 1
    zero = deque(k for k, v in in_degree.items() if v == 0)
    result: list[QualifiedName] = []
    while zero:
        n = zero.popleft()
        result.append(n)
        for m in out_edges[n]:
            in_degree[m] -= 1
            if in_degree[m] == 0:
                zero.append(m)
    if len(result) != len(names):
        return names
    return result


class SyncPlanBuilder:
    """
    Builds a SyncPlan from DiffResult and dialect.

    Does not emit DROP TABLE unless allow_drop_table is True. Does not emit
    DROP COLUMN unless allow_drop_column is True. Does not emit ALTER COLUMN
    when the change would shrink the column (e.g. reduce length) unless
    allow_shrink_column is True. Tables in DB but not in model are listed
    in plan.extra_tables for reporting only.
    """

    def __init__(
        self,
        dialect: Dialect,
        *,
        allow_drop_table: bool = False,
        allow_drop_column: bool = False,
        allow_drop_constraint: bool = True,
        allow_shrink_column: bool = False,
        report_extra_tables: bool = True,
    ) -> None:
        self.dialect = dialect
        self.allow_drop_table = allow_drop_table
        self.allow_drop_column = allow_drop_column
        self.allow_drop_constraint = allow_drop_constraint
        self.allow_shrink_column = allow_shrink_column
        self.report_extra_tables = report_extra_tables

    def build(self, diff: DiffResult) -> SyncPlan:
        """Produce an ordered SyncPlan from the diff."""
        steps: list[SyncStep] = []
        extra_tables: list[QualifiedName] = []

        if self.report_extra_tables:
            extra_tables = list(diff.removed_tables.keys())

        # Drop tables first (dependents before refs): reverse of create order.
        if self.allow_drop_table and diff.removed_tables:
            drop_order = list(
                reversed(_topological_table_order(diff.removed_tables))
            )
            for name in drop_order:
                if name not in diff.removed_tables:
                    continue
                sql = self.dialect.drop_table_sql(name)
                steps.append(
                    DropTableStep(
                        description=f"Drop table {name}",
                        sql=sql,
                        table_name=name,
                    )
                )

        order = _topological_table_order(diff.added_tables)
        for name in order:
            if name not in diff.added_tables:
                continue
            table = diff.added_tables[name]
            sql = self.dialect.create_table_sql(table)
            steps.append(
                CreateTableStep(
                    description=f"Create table {name}",
                    sql=sql,
                    table=table,
                )
            )

        for name, table_diff in diff.modified_tables.items():
            if self.allow_drop_constraint:
                for idx in table_diff.removed_indexes:
                    sql = self.dialect.drop_index_sql(idx.name, name)
                    steps.append(
                        AlterTableStep(
                            description=f"Drop index {idx.name} on {name}",
                            sql=sql,
                            table_name=name,
                        )
                    )
                for u in table_diff.removed_unique:
                    drop_sql = self.dialect.drop_unique_sql(name, u)
                    if drop_sql:
                        steps.append(
                            AlterTableStep(
                                description=f"Drop unique constraint on {name}",
                                sql=drop_sql,
                                table_name=name,
                                unique=u,
                            )
                        )
                for fk in table_diff.removed_foreign_keys:
                    drop_sql = self.dialect.drop_foreign_key_sql(name, fk)
                    if drop_sql:
                        steps.append(
                            AlterTableStep(
                                description=f"Drop foreign key on {name}",
                                sql=drop_sql,
                                table_name=name,
                            )
                        )
                for ck in table_diff.removed_checks:
                    drop_sql = self.dialect.drop_check_sql(name, ck)
                    if drop_sql:
                        steps.append(
                            AlterTableStep(
                                description=f"Drop check constraint on {name}",
                                sql=drop_sql,
                                table_name=name,
                            )
                        )
            if self.allow_drop_column:
                for col in table_diff.removed_columns:
                    drop_sql = self.dialect.drop_column_sql(name, col.name)
                    if drop_sql:
                        steps.append(
                            AlterTableStep(
                                description=f"Drop column {col.name} from {name}",
                                sql=drop_sql,
                                table_name=name,
                            )
                        )
            for col in table_diff.added_columns:
                sql = self.dialect.add_column_sql(name, col)
                steps.append(
                    AlterTableStep(
                        description=f"Add column {col.name} to {name}",
                        sql=sql,
                        table_name=name,
                        column=col,
                    )
                )
            for old_col, new_col in table_diff.modified_columns:
                alter_sql = self.dialect.alter_column_sql(name, old_col, new_col)
                if alter_sql:
                    if self.dialect.would_shrink(old_col, new_col) and not self.allow_shrink_column:
                        continue
                    steps.append(
                        AlterTableStep(
                            description=f"Alter column {new_col.name} on {name}",
                            sql=alter_sql,
                            table_name=name,
                            column=new_col,
                        )
                    )
            for u in table_diff.added_unique:
                sql = self.dialect.add_unique_sql(name, u)
                steps.append(
                    AlterTableStep(
                        description=f"Add unique constraint on {name}",
                        sql=sql,
                        table_name=name,
                        unique=u,
                    )
                )
            for fk in table_diff.added_foreign_keys:
                sql = self.dialect.add_foreign_key_sql(name, fk)
                steps.append(
                    AlterTableStep(
                        description=f"Add foreign key on {name}",
                        sql=sql,
                        table_name=name,
                    )
                )
            for ck in table_diff.added_checks:
                sql = self.dialect.add_check_sql(name, ck)
                steps.append(
                    AlterTableStep(
                        description=f"Add check constraint on {name}",
                        sql=sql,
                        table_name=name,
                    )
                )
            for idx in table_diff.added_indexes:
                sql = self.dialect.create_index_sql(idx, name)
                steps.append(
                    CreateIndexStep(
                        description=f"Create index {idx.name} on {name}",
                        sql=sql,
                        index=idx,
                        table_name=name,
                    )
                )

        return SyncPlan(steps=steps, extra_tables=extra_tables)
