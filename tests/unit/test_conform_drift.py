"""Unit tests: compare/apply_changes fail on error-severity skipped steps."""

from sqlalchemy import CheckConstraint, Column, Integer, MetaData, Table, create_engine

from dbconform import DbConform
from dbconform.errors import ConformError


def test_compare_returns_conform_error_for_missing_check_on_sqlite(tmp_path) -> None:
    """SQLite add CHECK skipped (rebuild disabled) is error-severity → ConformError."""
    db_path = tmp_path / "drift.db"
    engine = create_engine(f"sqlite:///{db_path}")

    live = MetaData()
    Table("items", live, Column("id", Integer, primary_key=True))
    live.create_all(engine)

    expected = MetaData()

    class ModelWithCheck:
        __table__ = Table(
            "items",
            expected,
            Column("id", Integer, primary_key=True),
            CheckConstraint("id > 0", name="items_id_positive"),
        )

    with engine.connect() as conn:
        conform = DbConform(connection=conn)
        result = conform.compare(
            [ModelWithCheck],
            allow_sqlite_table_rebuild=False,
        )
    assert isinstance(result, ConformError)
    assert result.plan is not None
    assert result.plan.has_blocking_skipped_steps()
    assert "check" in str(result).lower() or "constraint" in str(result).lower()
