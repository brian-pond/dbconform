"""
Unit tests for SchemaDiffer and differences().

Traceability: docs/requirements/01-functional.md (Plan and DDL order);
docs/technical/02-architecture.md. Scenarios: added, removed, modified tables.
"""


from modelsync.schema.diff import SchemaDiffer, differences
from modelsync.schema.objects import (
    ColumnDef,
    QualifiedName,
    TableDef,
)


def test_differences_added_removed_modified() -> None:
    """differences() returns added (in b not a), removed (in a not b), modified, unmodified."""
    a = {"x": 1, "y": 2, "z": 3}
    b = {"y": 2, "z": 99, "w": 4}
    added, removed, modified, unmodified = differences(a, b)
    assert list(added.keys()) == ["w"]
    assert added["w"] == 4
    assert list(removed.keys()) == ["x"]
    assert removed["x"] == 1
    assert list(modified.keys()) == ["z"]
    assert modified["z"] == 99
    assert list(unmodified.keys()) == ["y"]
    assert unmodified["y"] == 2


def test_schema_differ_added_table() -> None:
    """Model has table, DB does not -> added_tables (scenario 1)."""
    model_tables = {
        QualifiedName(None, "foo"): TableDef(
            name=QualifiedName(None, "foo"),
            columns=(ColumnDef("id", "INTEGER", nullable=False),),
        ),
    }
    db_tables: dict[QualifiedName, TableDef] = {}
    model_schema = type("M", (), {"tables": model_tables})()
    db_schema = type("D", (), {"tables": db_tables})()
    result = SchemaDiffer().diff(model_schema, db_schema)
    assert len(result.added_tables) == 1
    assert result.added_tables[QualifiedName(None, "foo")].name.name == "foo"
    assert len(result.removed_tables) == 0
    assert len(result.modified_tables) == 0


def test_schema_differ_removed_table() -> None:
    """DB has table, model does not -> removed_tables (scenario 2, report as extra)."""
    model_tables: dict[QualifiedName, TableDef] = {}
    db_tables = {
        QualifiedName(None, "orphan"): TableDef(
            name=QualifiedName(None, "orphan"),
            columns=(ColumnDef("id", "INTEGER", nullable=False),),
        ),
    }
    model_schema = type("M", (), {"tables": model_tables})()
    db_schema = type("D", (), {"tables": db_tables})()
    result = SchemaDiffer().diff(model_schema, db_schema)
    assert len(result.added_tables) == 0
    assert len(result.removed_tables) == 1
    assert result.removed_tables[QualifiedName(None, "orphan")].name.name == "orphan"
    assert len(result.modified_tables) == 0


def test_schema_differ_modified_table() -> None:
    """Both have table but different columns -> modified_tables (scenario 3)."""
    qualified = QualifiedName(None, "t")
    model_tables = {
        qualified: TableDef(
            name=qualified,
            columns=(
                ColumnDef("id", "INTEGER", nullable=False),
                ColumnDef("name", "VARCHAR(255)", nullable=False),
            ),
        ),
    }
    db_tables = {
        qualified: TableDef(
            name=qualified,
            columns=(ColumnDef("id", "INTEGER", nullable=False),),
        ),
    }
    model_schema = type("M", (), {"tables": model_tables})()
    db_schema = type("D", (), {"tables": db_tables})()
    result = SchemaDiffer().diff(model_schema, db_schema)
    assert len(result.added_tables) == 0
    assert len(result.removed_tables) == 0
    assert len(result.modified_tables) == 1
    td = result.modified_tables[qualified]
    assert len(td.added_columns) == 1
    assert td.added_columns[0].name == "name"
