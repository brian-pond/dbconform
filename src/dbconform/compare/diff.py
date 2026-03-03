"""
Compare model-side internal schema to database-side internal schema and produce a structured diff.

Uses the same added/removed/modified pattern as migra/results (db-to-db);
here "from" is DB and "target" is model so we drive toward the model.
See docs/technical/02-architecture.md and docs/requirements/01-functional.md
(Plan and DDL order).
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, TypeVar

from dbconform.internal.objects import (
    CheckDef,
    ColumnDef,
    ForeignKeyDef,
    IndexDef,
    QualifiedName,
    TableDef,
    UniqueDef,
)

K = TypeVar("K")
V = TypeVar("V")


def differences(
    a: Mapping[K, V],
    b: Mapping[K, V],
) -> tuple[OrderedDict[K, V], OrderedDict[K, V], OrderedDict[K, V], OrderedDict[K, V]]:
    """
    Compare two keyed structures; return added, removed, modified, unmodified.

    "Added" = in b not in a; "removed" = in a not in b;
    "modified" = in both but a[k] != b[k]; "unmodified" = in both and equal.
    Keys are sorted for deterministic ordering.
    """
    a_keys = set(a.keys())
    b_keys = set(b.keys())
    keys_added = b_keys - a_keys
    keys_removed = a_keys - b_keys
    keys_common = a_keys & b_keys

    def sort_key(k: K) -> tuple[str, str]:
        if isinstance(k, QualifiedName):
            return (k.schema or "", k.name)
        return (str(k), "")

    added = OrderedDict((k, b[k]) for k in sorted(keys_added, key=sort_key))
    removed = OrderedDict((k, a[k]) for k in sorted(keys_removed, key=sort_key))
    modified = OrderedDict((k, b[k]) for k in sorted(keys_common, key=sort_key) if a[k] != b[k])
    unmodified = OrderedDict((k, b[k]) for k in sorted(keys_common, key=sort_key) if a[k] == b[k])
    return added, removed, modified, unmodified


def _column_key(c: ColumnDef) -> str:
    return c.name


def _unique_key(u: UniqueDef) -> tuple[str | None, tuple[str, ...]]:
    return (u.name, u.column_names)


def _foreign_key_key(f: ForeignKeyDef) -> tuple[tuple[str, ...], str, tuple[str, ...]]:
    return (f.column_names, str(f.ref_table), f.ref_column_names)


def _check_key(c: CheckDef) -> tuple[str | None, str]:
    return (c.name, c.expression)


def _index_key(i: IndexDef) -> str:
    return i.name


def _build_dict_by_key(
    items: tuple[Any, ...],
    key_fn: Any,
) -> dict[Any, Any]:
    return {key_fn(x): x for x in items}


@dataclass(slots=True)
class TableDiff:
    """
    Per-table diff: what to add, remove, or alter.

    old_table: current DB state; new_table: desired model state.
    """

    old_table: TableDef
    new_table: TableDef
    added_columns: tuple[ColumnDef, ...] = ()
    removed_columns: tuple[ColumnDef, ...] = ()
    modified_columns: tuple[tuple[ColumnDef, ColumnDef], ...] = ()
    added_unique: tuple[UniqueDef, ...] = ()
    removed_unique: tuple[UniqueDef, ...] = ()
    modified_unique: tuple[tuple[UniqueDef, UniqueDef], ...] = ()
    added_foreign_keys: tuple[ForeignKeyDef, ...] = ()
    removed_foreign_keys: tuple[ForeignKeyDef, ...] = ()
    modified_foreign_keys: tuple[tuple[ForeignKeyDef, ForeignKeyDef], ...] = ()
    added_checks: tuple[CheckDef, ...] = ()
    removed_checks: tuple[CheckDef, ...] = ()
    modified_checks: tuple[tuple[CheckDef, CheckDef], ...] = ()
    added_indexes: tuple[IndexDef, ...] = ()
    removed_indexes: tuple[IndexDef, ...] = ()
    modified_indexes: tuple[tuple[IndexDef, IndexDef], ...] = ()


@dataclass(slots=True)
class DiffResult:
    """
    Result of comparing model-side internal schema (target) to database-side internal schema (current).

    - added_tables: in model, not in DB -> emit CREATE.
    - removed_tables: in DB, not in model -> do not DROP unless opt-in; report as "extra".
    - modified_tables: in both but different -> emit ALTER per TableDiff.
    """

    added_tables: OrderedDict[QualifiedName, TableDef] = field(default_factory=OrderedDict)
    removed_tables: OrderedDict[QualifiedName, TableDef] = field(default_factory=OrderedDict)
    modified_tables: OrderedDict[QualifiedName, TableDiff] = field(default_factory=OrderedDict)


def _diff_columns(
    old_cols: dict[str, ColumnDef],
    new_cols: dict[str, ColumnDef],
) -> tuple[list[ColumnDef], list[ColumnDef], list[tuple[ColumnDef, ColumnDef]]]:
    added = [new_cols[k] for k in new_cols if k not in old_cols]
    removed = [old_cols[k] for k in old_cols if k not in new_cols]
    modified = [(old_cols[k], new_cols[k]) for k in old_cols if k in new_cols and old_cols[k] != new_cols[k]]
    return added, removed, modified


def _diff_uniques(
    old: TableDef,
    new: TableDef,
) -> tuple[list[UniqueDef], list[UniqueDef], list[tuple[UniqueDef, UniqueDef]]]:
    old_d = _build_dict_by_key(old.unique_constraints, _unique_key)
    new_d = _build_dict_by_key(new.unique_constraints, _unique_key)
    added = [new_d[k] for k in new_d if k not in old_d]
    removed = [old_d[k] for k in old_d if k not in new_d]
    modified = [(old_d[k], new_d[k]) for k in old_d if k in new_d and old_d[k] != new_d[k]]
    return added, removed, modified


def _diff_fks(
    old: TableDef,
    new: TableDef,
) -> tuple[list[ForeignKeyDef], list[ForeignKeyDef], list[tuple[ForeignKeyDef, ForeignKeyDef]]]:
    old_d = _build_dict_by_key(old.foreign_keys, _foreign_key_key)
    new_d = _build_dict_by_key(new.foreign_keys, _foreign_key_key)
    added = [new_d[k] for k in new_d if k not in old_d]
    removed = [old_d[k] for k in old_d if k not in new_d]
    modified = [(old_d[k], new_d[k]) for k in old_d if k in new_d and old_d[k] != new_d[k]]
    return added, removed, modified


def _diff_checks(
    old: TableDef,
    new: TableDef,
) -> tuple[list[CheckDef], list[CheckDef], list[tuple[CheckDef, CheckDef]]]:
    old_d = _build_dict_by_key(old.check_constraints, _check_key)
    new_d = _build_dict_by_key(new.check_constraints, _check_key)
    added = [new_d[k] for k in new_d if k not in old_d]
    removed = [old_d[k] for k in old_d if k not in new_d]
    modified = [(old_d[k], new_d[k]) for k in old_d if k in new_d and old_d[k] != new_d[k]]
    return added, removed, modified


def _diff_indexes(
    old: TableDef,
    new: TableDef,
) -> tuple[list[IndexDef], list[IndexDef], list[tuple[IndexDef, IndexDef]]]:
    old_d = _build_dict_by_key(old.indexes, _index_key)
    new_d = _build_dict_by_key(new.indexes, _index_key)
    added = [new_d[k] for k in new_d if k not in old_d]
    removed = [old_d[k] for k in old_d if k not in new_d]
    modified = [(old_d[k], new_d[k]) for k in old_d if k in new_d and old_d[k] != new_d[k]]
    return added, removed, modified


def _build_table_diff(old_table: TableDef, new_table: TableDef) -> TableDiff:
    """Build a TableDiff between old (DB) and new (model) table."""
    old_cols = old_table.column_by_name()
    new_cols = new_table.column_by_name()
    added_cols, removed_cols, modified_cols = _diff_columns(old_cols, new_cols)
    added_uniques, removed_uniques, modified_uniques = _diff_uniques(old_table, new_table)
    added_fks, removed_fks, modified_fks = _diff_fks(old_table, new_table)
    added_checks, removed_checks, modified_checks = _diff_checks(old_table, new_table)
    added_indexes, removed_indexes, modified_indexes = _diff_indexes(old_table, new_table)
    return TableDiff(
        old_table=old_table,
        new_table=new_table,
        added_columns=tuple(added_cols),
        removed_columns=tuple(removed_cols),
        modified_columns=tuple(modified_cols),
        added_unique=tuple(added_uniques),
        removed_unique=tuple(removed_uniques),
        modified_unique=tuple(modified_uniques),
        added_foreign_keys=tuple(added_fks),
        removed_foreign_keys=tuple(removed_fks),
        modified_foreign_keys=tuple(modified_fks),
        added_checks=tuple(added_checks),
        removed_checks=tuple(removed_checks),
        modified_checks=tuple(modified_checks),
        added_indexes=tuple(added_indexes),
        removed_indexes=tuple(removed_indexes),
        modified_indexes=tuple(modified_indexes),
    )


class SchemaDiffer:
    """
    Compares model-side internal schema (target) to database-side internal schema (current).

    Produces DiffResult: added_tables, removed_tables, modified_tables.
    """

    def diff(
        self,
        model_schema: Any,
        db_schema: Any,
    ) -> DiffResult:
        """
        Compare model-side internal schema to database-side internal schema.

        model_schema and db_schema must have .tables: dict[QualifiedName, TableDef].
        """
        # Convention: a = current (DB), b = target (model)
        added, removed, modified, _ = differences(
            db_schema.tables,
            model_schema.tables,
        )
        modified_diffs: OrderedDict[QualifiedName, TableDiff] = OrderedDict()
        for name, new_table in modified.items():
            old_table = db_schema.tables[name]
            modified_diffs[name] = _build_table_diff(old_table, new_table)
        return DiffResult(
            added_tables=added,
            removed_tables=removed,
            modified_tables=modified_diffs,
        )
