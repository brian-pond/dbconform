"""
Unit tests for dbconform.integrations.dbt.generate_schema_yml.

Tests compare expected YAML (parsed back to dicts) against actual output to
avoid false failures from YAML key ordering or whitespace differences.

Traceability: docs/requirements/01-functional.md (BR-DBT-002 – BR-DBT-005).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml
from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase

from dbconform.integrations.dbt import generate_schema_yml


# ---------------------------------------------------------------------------
# Shared declarative base and model fixtures
# ---------------------------------------------------------------------------


class _Base(DeclarativeBase):
    """Shared base for test models — keeps metadata isolated from other tests."""


class _User(_Base):
    """Simple model: PK, not-null column, nullable column, comment."""

    __tablename__ = "user"
    __table_args__ = {"comment": "Application users"}

    id: int = Column(Integer, primary_key=True, comment="User primary key")
    username: str = Column(String(100), nullable=False, comment="Unique login name")
    bio: str | None = Column(String(500), nullable=True)


class _Order(_Base):
    """Model with a FK to _User and a non-nullable column."""

    __tablename__ = "order"

    id: int = Column(Integer, primary_key=True)
    user_id: int = Column(Integer, ForeignKey("user.id"), nullable=False)
    status: str = Column(String(50), nullable=False)
    notes: str | None = Column(String(255), nullable=True)


class _Product(_Base):
    """Model with a named single-column unique constraint."""

    __tablename__ = "product"
    __table_args__ = (UniqueConstraint("sku", name="uq_product_sku"),)

    id: int = Column(Integer, primary_key=True)
    sku: str = Column(String(64), nullable=False)
    name: str = Column(String(200), nullable=False)


class _Combo(_Base):
    """Model with a multi-column unique constraint (requires dbt_utils note)."""

    __tablename__ = "combo"
    __table_args__ = (UniqueConstraint("col_a", "col_b", name="uq_combo_ab"),)

    id: int = Column(Integer, primary_key=True)
    col_a: str = Column(String(50), nullable=False)
    col_b: str = Column(String(50), nullable=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse(yaml_str: str) -> dict:
    """Parse YAML string to dict for structural comparison."""
    return yaml.safe_load(yaml_str)


def _model_by_name(doc: dict, name: str) -> dict:
    """Return the models entry matching ``name``."""
    return next(m for m in doc["models"] if m["name"] == name)


def _col_by_name(model: dict, name: str) -> dict:
    """Return the columns entry matching ``name``."""
    return next(c for c in model["columns"] if c["name"] == name)


def _col_tests(col: dict) -> list:
    """Return the data_tests list for a column (dbt v1.8+ key)."""
    return col.get("data_tests", [])


# ---------------------------------------------------------------------------
# BR-DBT-003: not_null tests
# ---------------------------------------------------------------------------


class TestNotNull:
    """BR-DBT-003: not_null is emitted for non-nullable non-PK columns."""

    def test_non_nullable_column_gets_not_null(self) -> None:
        yaml_str = generate_schema_yml(_User)
        assert yaml_str is not None
        doc = _parse(yaml_str)
        model = _model_by_name(doc, "user")
        username_col = _col_by_name(model, "username")
        assert "not_null" in _col_tests(username_col)

    def test_nullable_column_has_no_not_null(self) -> None:
        yaml_str = generate_schema_yml(_User)
        assert yaml_str is not None
        doc = _parse(yaml_str)
        model = _model_by_name(doc, "user")
        bio_col = _col_by_name(model, "bio")
        assert "not_null" not in _col_tests(bio_col)


# ---------------------------------------------------------------------------
# BR-DBT-003: PK columns get not_null + unique
# ---------------------------------------------------------------------------


class TestPrimaryKey:
    """BR-DBT-003: PK columns receive not_null and unique tests."""

    def test_pk_column_has_not_null_and_unique(self) -> None:
        yaml_str = generate_schema_yml(_User)
        assert yaml_str is not None
        doc = _parse(yaml_str)
        model = _model_by_name(doc, "user")
        id_col = _col_by_name(model, "id")
        assert "not_null" in _col_tests(id_col)
        assert "unique" in _col_tests(id_col)


# ---------------------------------------------------------------------------
# BR-DBT-003: unique tests from UniqueConstraint
# ---------------------------------------------------------------------------


class TestUniqueConstraint:
    """BR-DBT-003: single-column UniqueConstraint emits unique test on the column."""

    def test_single_column_unique_emitted(self) -> None:
        yaml_str = generate_schema_yml(_Product)
        assert yaml_str is not None
        doc = _parse(yaml_str)
        model = _model_by_name(doc, "product")
        sku_col = _col_by_name(model, "sku")
        assert "unique" in _col_tests(sku_col)

    def test_multi_column_unique_not_emitted_as_test(self) -> None:
        """Multi-column unique must NOT produce a unique test on individual columns."""
        yaml_str = generate_schema_yml(_Combo)
        assert yaml_str is not None
        doc = _parse(yaml_str)
        model = _model_by_name(doc, "combo")
        for col_name in ("col_a", "col_b"):
            col = _col_by_name(model, col_name)
            assert "unique" not in _col_tests(col), f"Unexpected unique on {col_name}"

    def test_multi_column_unique_emits_meta_note(self) -> None:
        """Multi-column unique must produce a dbconform_notes entry (BR-DBT-003)."""
        yaml_str = generate_schema_yml(_Combo)
        assert yaml_str is not None
        doc = _parse(yaml_str)
        model = _model_by_name(doc, "combo")
        notes = model.get("meta", {}).get("dbconform_notes", [])
        assert any("col_a" in n and "col_b" in n for n in notes), (
            "Expected a multi-column unique note mentioning col_a and col_b"
        )
        assert any("dbt_utils" in n for n in notes), (
            "Expected note to mention dbt_utils"
        )


# ---------------------------------------------------------------------------
# BR-DBT-003: FK relationships test
# ---------------------------------------------------------------------------


class TestForeignKey:
    """BR-DBT-003, BR-DBT-007: FK columns get relationships tests with ref()."""

    def test_fk_column_gets_relationships_test(self) -> None:
        yaml_str = generate_schema_yml(_Order)
        assert yaml_str is not None
        doc = _parse(yaml_str)
        model = _model_by_name(doc, "order")
        user_id_col = _col_by_name(model, "user_id")
        rel_tests = [t for t in _col_tests(user_id_col) if isinstance(t, dict) and "relationships" in t]
        assert len(rel_tests) == 1
        rel = rel_tests[0]["relationships"]
        assert rel["to"] == "ref('user')"
        assert rel["field"] == "id"

    def test_fk_column_also_has_not_null(self) -> None:
        """FK column that is NOT NULL should have both not_null and relationships."""
        yaml_str = generate_schema_yml(_Order)
        assert yaml_str is not None
        doc = _parse(yaml_str)
        model = _model_by_name(doc, "order")
        user_id_col = _col_by_name(model, "user_id")
        assert "not_null" in _col_tests(user_id_col)


# ---------------------------------------------------------------------------
# BR-DBT-003: descriptions from comments
# ---------------------------------------------------------------------------


class TestDescriptions:
    """BR-DBT-003: table comment → model description; column comment → column description."""

    def test_table_comment_becomes_model_description(self) -> None:
        yaml_str = generate_schema_yml(_User)
        assert yaml_str is not None
        doc = _parse(yaml_str)
        model = _model_by_name(doc, "user")
        assert model.get("description") == "Application users"

    def test_column_comment_becomes_column_description(self) -> None:
        yaml_str = generate_schema_yml(_User)
        assert yaml_str is not None
        doc = _parse(yaml_str)
        model = _model_by_name(doc, "user")
        id_col = _col_by_name(model, "id")
        assert id_col.get("description") == "User primary key"

    def test_column_without_comment_has_no_description(self) -> None:
        yaml_str = generate_schema_yml(_Order)
        assert yaml_str is not None
        doc = _parse(yaml_str)
        model = _model_by_name(doc, "order")
        id_col = _col_by_name(model, "id")
        assert "description" not in id_col


# ---------------------------------------------------------------------------
# BR-DBT-004: output modes (unified, per-model, return string)
# ---------------------------------------------------------------------------


class TestOutputModes:
    """BR-DBT-004: generate_schema_yml supports string return, file write, per-model."""

    def test_single_model_returns_str(self) -> None:
        result = generate_schema_yml(_User)
        assert isinstance(result, str)
        assert result.strip()

    def test_multiple_models_unified_string(self) -> None:
        result = generate_schema_yml([_User, _Order])
        assert isinstance(result, str)
        doc = _parse(result)
        names = {m["name"] for m in doc["models"]}
        assert names == {"user", "order"}

    def test_unified_file_write(self, tmp_path: Path) -> None:
        output = tmp_path / "schema.yml"
        result = generate_schema_yml([_User, _Order], output_path=output)
        assert result is None
        assert output.exists()
        doc = _parse(output.read_text())
        assert doc["version"] == 2
        assert len(doc["models"]) == 2

    def test_per_model_files(self, tmp_path: Path) -> None:
        result = generate_schema_yml([_User, _Order], output_dir=tmp_path, per_model=True)
        assert result is None
        user_file = tmp_path / "user.schema.yml"
        order_file = tmp_path / "order.schema.yml"
        assert user_file.exists()
        assert order_file.exists()
        user_doc = _parse(user_file.read_text())
        assert len(user_doc["models"]) == 1
        assert user_doc["models"][0]["name"] == "user"
        order_doc = _parse(order_file.read_text())
        assert order_doc["models"][0]["name"] == "order"

    def test_output_path_and_output_dir_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="mutually exclusive"):
            generate_schema_yml(_User, output_path=tmp_path / "x.yml", output_dir=tmp_path)

    def test_per_model_without_output_dir_raises(self) -> None:
        with pytest.raises(ValueError, match="output_dir"):
            generate_schema_yml(_User, per_model=True)


# ---------------------------------------------------------------------------
# BR-DBT-004, BR-DBT-005: document structure
# ---------------------------------------------------------------------------


class TestDocumentStructure:
    """Schema.yml must always start with version: 2 and have a models key."""

    def test_top_level_version_is_2(self) -> None:
        doc = _parse(generate_schema_yml(_User))  # type: ignore[arg-type]
        assert doc["version"] == 2

    def test_models_key_present(self) -> None:
        doc = _parse(generate_schema_yml(_User))  # type: ignore[arg-type]
        assert "models" in doc
        assert isinstance(doc["models"], list)

    def test_all_columns_present(self) -> None:
        doc = _parse(generate_schema_yml(_User))  # type: ignore[arg-type]
        model = _model_by_name(doc, "user")
        col_names = {c["name"] for c in model["columns"]}
        assert col_names == {"id", "username", "bio"}


# ---------------------------------------------------------------------------
# Expected YAML comparison (exact content, parsed)
# ---------------------------------------------------------------------------


class TestExpectedYaml:
    """
    Exact structural comparison: expected YAML dict vs actual parsed output.

    This is the authoritative set of assertions for regression detection.
    Traceability: BR-DBT-002 – BR-DBT-005.
    """

    def test_user_model_expected_yaml(self) -> None:
        expected_yaml = textwrap.dedent("""\
            version: 2
            models:
              - name: user
                description: Application users
                columns:
                  - name: id
                    description: User primary key
                    data_tests:
                      - not_null
                      - unique
                  - name: username
                    description: Unique login name
                    data_tests:
                      - not_null
                  - name: bio
        """)
        expected = yaml.safe_load(expected_yaml)
        actual = yaml.safe_load(generate_schema_yml(_User))  # type: ignore[arg-type]
        assert actual == expected

    def test_order_model_expected_yaml(self) -> None:
        expected_yaml = textwrap.dedent("""\
            version: 2
            models:
              - name: order
                columns:
                  - name: id
                    data_tests:
                      - not_null
                      - unique
                  - name: user_id
                    data_tests:
                      - not_null
                      - relationships:
                          to: ref('user')
                          field: id
                  - name: status
                    data_tests:
                      - not_null
                  - name: notes
        """)
        expected = yaml.safe_load(expected_yaml)
        actual = yaml.safe_load(generate_schema_yml(_Order))  # type: ignore[arg-type]
        assert actual == expected

    def test_product_model_expected_yaml(self) -> None:
        """Single-column unique constraint on sku emits unique on sku (not on id again)."""
        expected_yaml = textwrap.dedent("""\
            version: 2
            models:
              - name: product
                columns:
                  - name: id
                    data_tests:
                      - not_null
                      - unique
                  - name: sku
                    data_tests:
                      - not_null
                      - unique
                  - name: name
                    data_tests:
                      - not_null
        """)
        expected = yaml.safe_load(expected_yaml)
        actual = yaml.safe_load(generate_schema_yml(_Product))  # type: ignore[arg-type]
        assert actual == expected
