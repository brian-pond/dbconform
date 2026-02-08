"""
Unit test: simple model column definitions.

Traceability: docs/requirements/01-functional.md — Model discovery.
"""

from typing import get_type_hints

from tests.shared_models import SimpleRecord


def test_simple_model_has_expected_columns() -> None:
    """Verify the simple model defines one table with string, float, and integer columns."""
    assert SimpleRecord.__tablename__ == "simple_record"
    assert hasattr(SimpleRecord, "id") and hasattr(SimpleRecord, "name")
    assert hasattr(SimpleRecord, "value") and hasattr(SimpleRecord, "count")
    hints = get_type_hints(SimpleRecord)
    assert hints["name"] is str
    assert hints["value"] is float
    assert hints["count"] is int
