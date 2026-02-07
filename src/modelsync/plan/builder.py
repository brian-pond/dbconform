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

    Does not emit DROP unless allow_drop_table is True. Tables in DB but not
    in model are recorded in plan.extra_tables for reporting only.
    """

    def __init__(
        self,
        dialect: Dialect,
        *,
        allow_drop_table: bool = False,
        report_extra_tables: bool = True,
    ) -> None:
        self.dialect = dialect
        self.allow_drop_table = allow_drop_table
        self.report_extra_tables = report_extra_tables

    def build(self, diff: DiffResult) -> SyncPlan:
        """Produce an ordered SyncPlan from the diff."""
        steps: list[SyncStep] = []
        extra_tables: list[QualifiedName] = []

        if self.report_extra_tables:
            extra_tables = list(diff.removed_tables.keys())

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
