"""
dbt schema.yml generation from dbconform internal schema objects.

Converts ``TableDef`` instances to a dbt ``schema.yml`` (version 2) YAML document.
Requires the ``[dbt]`` extra (``pyyaml>=6``).

Traceability: docs/requirements/01-functional.md (BR-DBT-002 – BR-DBT-005).
"""

from __future__ import annotations

try:
    import yaml
except ImportError as _e:
    raise ImportError(
        "dbconform[dbt] is required for dbt integration. "
        "Install with: pip install 'dbconform[dbt]'"
    ) from _e

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from dbconform.adapters.model_schema import ModelSchema
from dbconform.internal.objects import TableDef


# ---------------------------------------------------------------------------
# Internal: TableDef → dbt YAML dict
# ---------------------------------------------------------------------------


def _tests_for_column(col_name: str, table: TableDef) -> list[Any]:
    """
    Collect dbt test entries for a single column.

    Applies: not_null (BR-DBT-003), unique (BR-DBT-003), relationships / FK
    (BR-DBT-003). PK columns receive not_null + unique per BR-DBT-003.
    Deduplicates unique tests when both a UniqueDef and an IndexDef cover the
    same single column.
    """
    tests: list[Any] = []
    added_unique = False

    # Primary key columns → not_null + unique
    pk = table.primary_key
    if pk and col_name in pk.column_names:
        tests.append("not_null")
        tests.append("unique")
        added_unique = True
        return tests  # PK columns: no further nullable check needed

    # Nullable: not_null test
    col = next((c for c in table.columns if c.name == col_name), None)
    if col and not col.nullable:
        tests.append("not_null")

    # Single-column unique constraints (BR-DBT-003)
    for udef in table.unique_constraints:
        if len(udef.column_names) == 1 and udef.column_names[0] == col_name:
            if not added_unique:
                tests.append("unique")
                added_unique = True

    # Single-column unique indexes (BR-DBT-003, deduplicated)
    for idx in table.indexes:
        if idx.unique and len(idx.column_names) == 1 and idx.column_names[0] == col_name:
            if not added_unique:
                tests.append("unique")
                added_unique = True

    # Foreign key relationships (BR-DBT-003, BR-DBT-007)
    for fk in table.foreign_keys:
        if col_name in fk.column_names:
            col_pos = list(fk.column_names).index(col_name)
            ref_col = str(fk.ref_column_names[col_pos])
            ref_table = str(fk.ref_table.name)
            tests.append(
                {
                    "relationships": {
                        "to": f"ref('{ref_table}')",
                        "field": ref_col,
                    }
                }
            )

    return tests


def _multi_column_unique_comments(table: TableDef) -> list[str]:
    """
    Return comment strings for multi-column unique constraints (BR-DBT-003).

    dbt's built-in tests do not support multi-column unique; callers need
    ``dbt_utils.unique_combination_of_columns``.
    """
    comments: list[str] = []
    for udef in table.unique_constraints:
        if len(udef.column_names) > 1:
            cols = ", ".join(str(c) for c in udef.column_names)
            comments.append(
                f"Multi-column unique constraint ({cols}) requires "
                "dbt_utils.unique_combination_of_columns — add manually."
            )
    return comments


def _table_def_to_dbt_model(table: TableDef) -> dict[str, Any]:
    """
    Convert a single ``TableDef`` to a dbt model dict (BR-DBT-002, BR-DBT-003).

    The dict matches the dbt ``schema.yml`` ``models[*]`` structure.

    Note: SQLAlchemy stores table and column names as ``quoted_name`` (a ``str`` subclass).
    PyYAML serializes subclasses with Python-specific tags, so all names are coerced to
    plain ``str`` before building the YAML dict.
    """
    model: dict[str, Any] = {"name": str(table.name.name)}
    if table.comment:
        model["description"] = str(table.comment)

    columns: list[dict[str, Any]] = []
    for col in table.columns:
        col_name = str(col.name)
        col_dict: dict[str, Any] = {"name": col_name}
        if col.comment:
            col_dict["description"] = str(col.comment)
        tests = _tests_for_column(col_name, table)
        if tests:
            # dbt renamed "tests:" to "data_tests:" in v1.8 (current best practice).
            col_dict["data_tests"] = tests
        columns.append(col_dict)

    if columns:
        model["columns"] = columns

    # Attach multi-column unique comments as top-level model meta note (BR-DBT-003)
    multi_unique_notes = _multi_column_unique_comments(table)
    if multi_unique_notes:
        model.setdefault("meta", {})["dbconform_notes"] = multi_unique_notes

    return model


def _build_schema_doc(tables: Sequence[TableDef]) -> dict[str, Any]:
    """
    Build the top-level dbt ``schema.yml`` dict for one or more tables.

    See docs/requirements/01-functional.md (BR-DBT-004).
    """
    return {
        "version": 2,
        "models": [_table_def_to_dbt_model(t) for t in tables],
    }


def _to_yaml_str(doc: dict[str, Any]) -> str:
    """Serialize a dbt schema dict to a YAML string."""
    return yaml.dump(doc, sort_keys=False, allow_unicode=True, default_flow_style=False)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_schema_yml(
    models: type | Sequence[type],
    *,
    output_path: Path | None = None,
    output_dir: Path | None = None,
    per_model: bool = False,
    target_schema: str | None = None,
) -> str | None:
    """
    Generate dbt ``schema.yml`` content from one or more SQLAlchemy/SQLModel models.

    Parameters
    ----------
    models:
        A single model class or a sequence of model classes (must have ``__table__``).
    output_path:
        When set, write a unified ``schema.yml`` to this path and return ``None``.
        Mutually exclusive with ``output_dir`` / ``per_model``.
    output_dir:
        When set with ``per_model=True``, write one ``<table>.schema.yml`` per model
        into this directory and return ``None``.
    per_model:
        When ``True`` and ``output_dir`` is set, produce one file per model.
    target_schema:
        Passed to ``ModelSchema.from_models()``; used when table.schema is ``None``
        (e.g. PostgreSQL public schema).

    Returns
    -------
    str | None
        YAML string when no output path/dir is given; ``None`` when writing files.

    Raises
    ------
    ValueError
        When ``output_path`` and ``output_dir``/``per_model`` are both set, or when
        ``per_model`` is set without ``output_dir``.

    See Also
    --------
    docs/requirements/01-functional.md : BR-DBT-004, BR-DBT-005.
    """
    if output_path is not None and (output_dir is not None or per_model):
        raise ValueError("output_path and output_dir/per_model are mutually exclusive.")
    if per_model and output_dir is None:
        raise ValueError("per_model=True requires output_dir to be set.")

    model_schema = ModelSchema.from_models(models, target_schema)
    tables = list(model_schema.tables.values())

    if per_model and output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        for table in tables:
            doc = _build_schema_doc([table])
            path = output_dir / f"{table.name.name}.schema.yml"
            path.write_text(_to_yaml_str(doc), encoding="utf-8")
        return None

    doc = _build_schema_doc(tables)
    yaml_str = _to_yaml_str(doc)

    if output_path is not None:
        Path(output_path).write_text(yaml_str, encoding="utf-8")
        return None

    return yaml_str
