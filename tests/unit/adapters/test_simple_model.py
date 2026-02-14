"""
Unit test: simple model column definitions.

Traceability: docs/requirements/01-functional.md — Model discovery;
docs/technical/02-architecture.md (Core functions: Adapters ingest).
"""

from typing import get_type_hints

from tests.shared_models import SimpleTable


def test_simple_model_has_expected_columns() -> None:
    """Verify the simple model defines one table with string, float, and integer columns."""
    assert SimpleTable.__tablename__ == "simple_table"
    assert hasattr(SimpleTable, "id") and hasattr(SimpleTable, "name")
    assert hasattr(SimpleTable, "value") and hasattr(SimpleTable, "count")
    hints = get_type_hints(SimpleTable)
    assert hints["name"] is str
    assert hints["value"] is float
    assert hints["count"] is int
