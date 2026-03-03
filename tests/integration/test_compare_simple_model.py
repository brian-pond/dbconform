"""
Integration tests: DbConform.compare() and apply_changes() against a real database
(SQLite and PostgreSQL via empty_db).

Traceability: docs/requirements/01-functional.md — Model discovery and API,
Database connection, compare() / apply_changes(). Acceptance: schema (create tables, columns).
"""

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

import dbconform
from tests.shared_models import SimpleTable, SimpleTableWithIndex, SimpleTableWithUnique


def test_empty_sqlite_db_fixture(empty_sqlite_db: tuple[Path, str]) -> None:
    """Use empty_sqlite_db fixture: DB exists, is writable, and can have tables created."""
    path, url = empty_sqlite_db
    assert isinstance(path, Path)
    assert path.suffix == ".db"
    assert path.exists()

    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY)"))
        conn.commit()
        result = conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))
        names = [row[0] for row in result]
    engine.dispose()
    assert "t" in names


def test_empty_postgres_db_fixture(empty_postgres_db: tuple[str, str]) -> None:
    """Use empty_postgres_db fixture: DB exists, is writable, and can have tables created.
    Skips when DBCONFORM_TEST_POSTGRES_URL is not set (01-functional: database connection)."""
    url, schema = empty_postgres_db
    assert schema == "public"
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text("CREATE TABLE t (id SERIAL PRIMARY KEY)")
        )
        conn.commit()
        result = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 't'"
            )
        )
        rows = list(result)
    engine.dispose()
    assert len(rows) == 1
    assert rows[0][0] == "t"


def test_compare_empty_db_returns_create_step(empty_db: tuple[str, str | None]) -> None:
    """Scenario 1: model has table, DB does not — plan contains CREATE TABLE (01-functional)."""
    url, target_schema = empty_db
    conform = dbconform.DbConform(credentials={"url": url}, target_schema=target_schema)
    result = conform.compare(SimpleTable)
    assert not isinstance(result, dbconform.ConformError), str(result)
    plan = result
    assert len(plan.steps) == 1
    assert "simple_table" in plan.sql()
    assert "CREATE TABLE" in plan.sql()


def test_compare_with_connection(empty_db: tuple[str, str | None]) -> None:
    """Caller passes connection; compare returns plan (01-functional: pass existing connection)."""
    url, target_schema = empty_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conform = dbconform.DbConform(connection=conn, target_schema=target_schema)
        result = conform.compare(SimpleTable)
    engine.dispose()
    assert not isinstance(result, dbconform.ConformError)
    assert len(result.steps) == 1


def test_apply_changes_with_connection_caller_closes(empty_db: tuple[str, str | None]) -> None:
    """Caller passes connection; apply_changes applies plan; caller closes connection (01-functional)."""
    url, target_schema = empty_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conform = dbconform.DbConform(connection=conn, target_schema=target_schema)
        result = conform.apply_changes(SimpleTable)
    engine.dispose()
    assert not isinstance(result, dbconform.ConformError), str(result)
    assert len(result.steps) == 1
    # Reopen and recompare to confirm schema parity
    engine2 = create_engine(url)
    with engine2.connect() as conn2:
        conform2 = dbconform.DbConform(connection=conn2, target_schema=target_schema)
        recompare = conform2.compare(SimpleTable)
    engine2.dispose()
    assert not isinstance(recompare, dbconform.ConformError)
    assert len(recompare.steps) == 0


def test_compare_after_create_same_schema_no_steps(empty_db: tuple[str, str | None]) -> None:
    """Scenario 3: table exists in DB and matches model — no steps (schema parity)."""
    url, target_schema = empty_db
    conform = dbconform.DbConform(credentials={"url": url}, target_schema=target_schema)
    conform.apply_changes(SimpleTable)
    result = conform.compare(SimpleTable)
    assert not isinstance(result, dbconform.ConformError)
    assert len(result.steps) == 0


def test_compare_extra_table_in_db_reported_not_dropped(empty_db: tuple[str, str | None]) -> None:
    """Scenario 2: DB has table not in model — reported in extra_tables, no DROP (01-functional)."""
    url, target_schema = empty_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE other_table (id INTEGER PRIMARY KEY)"))
        conn.commit()
    with engine.connect() as conn:
        conform = dbconform.DbConform(connection=conn, target_schema=target_schema)
        result = conform.compare(SimpleTable)
    engine.dispose()
    assert not isinstance(result, dbconform.ConformError)
    assert len(result.extra_tables) == 1
    assert result.extra_tables[0].name == "other_table"
    assert not any("DROP" in (s.sql or "") for s in result.steps)


def test_apply_changes_applies_plan_then_recompare_parity(empty_db: tuple[str, str | None]) -> None:
    """Table missing; apply_changes applies CREATE; recompare yields 0 steps (01-functional)."""
    url, target_schema = empty_db
    conform = dbconform.DbConform(credentials={"url": url}, target_schema=target_schema)
    result = conform.apply_changes(SimpleTable)
    assert not isinstance(result, dbconform.ConformError), str(result)
    plan = result
    assert len(plan.steps) == 1
    assert "CREATE TABLE" in plan.sql()
    recompare = conform.compare(SimpleTable)
    assert not isinstance(recompare, dbconform.ConformError)
    assert len(recompare.steps) == 0


def test_compare_invalid_model_returns_conform_error(empty_db: tuple[str, str | None]) -> None:
    """Passing a class with no __table__ returns ConformError (01-functional: Error handling)."""
    url, target_schema = empty_db
    conform = dbconform.DbConform(credentials={"url": url}, target_schema=target_schema)

    class NotATable:
        """Plain class; no __table__, not a mapped model."""

    result = conform.compare(NotATable)
    assert isinstance(result, dbconform.ConformError)
    assert len(result.messages) >= 1
    assert len(result.target_objects) >= 1, (
        "ConformError must identify which target failed (01-functional: Error handling)"
    )


def test_apply_changes_apply_failure_returns_conform_error_with_target_objects(
    empty_sqlite_db: tuple[Path, str],
) -> None:
    """When a plan step fails during apply (e.g. unsupported SQL on SQLite), apply_changes returns
    ConformError with target_objects (01-functional: Error handling)."""
    _path, url = empty_sqlite_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE simple_table_with_unique ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(255) NOT NULL, "
                "value FLOAT NOT NULL, count INTEGER NOT NULL)"
            )
        )
        conn.commit()
    engine.dispose()

    # SimpleTableWithUnique adds UNIQUE(name); SQLite does not support ALTER TABLE ADD CONSTRAINT.
    conform = dbconform.DbConform(credentials={"url": url}, target_schema=None)
    result = conform.apply_changes(SimpleTableWithUnique)
    assert isinstance(result, dbconform.ConformError)
    assert len(result.messages) >= 1
    assert len(result.target_objects) >= 1
    assert any(obj[0] == "table" or obj[0] == "step" for obj in result.target_objects)


def test_apply_changes_apply_failure_returns_conform_error_with_target_objects_postgres(
    empty_postgres_db: tuple[str, str],
) -> None:
    """When a plan step fails during apply (e.g. SET NOT NULL with existing NULLs),
    apply_changes returns ConformError with target_objects (01-functional: Error handling)."""
    url, schema = empty_postgres_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE simple_table ("
                "id SERIAL PRIMARY KEY, name VARCHAR(255), "
                "value DOUBLE PRECISION NOT NULL, count INTEGER NOT NULL)"
            )
        )
        conn.execute(
            text("INSERT INTO simple_table (name, value, count) VALUES (NULL, 1.0, 0)")
        )
        conn.commit()
    engine.dispose()

    # SimpleTable has name NOT NULL; DB has NULL in name. ALTER COLUMN SET NOT NULL fails.
    conform = dbconform.DbConform(credentials={"url": url}, target_schema=schema)
    result = conform.apply_changes(SimpleTable)
    assert isinstance(result, dbconform.ConformError)
    assert len(result.messages) >= 1
    assert len(result.target_objects) >= 1
    assert any(obj[0] == "table" or obj[0] == "step" for obj in result.target_objects)


def test_apply_changes_commit_per_step_succeeds(empty_db: tuple[str, str | None]) -> None:
    """apply_changes(..., commit_per_step=True) applies plan and commits after each step
    (01-functional: Transaction behavior)."""
    url, target_schema = empty_db
    conform = dbconform.DbConform(credentials={"url": url}, target_schema=target_schema)
    result = conform.apply_changes(SimpleTable, commit_per_step=True)
    assert not isinstance(result, dbconform.ConformError)
    recompare = conform.compare(SimpleTable)
    assert not isinstance(recompare, dbconform.ConformError)
    assert len(recompare.steps) == 0


def test_apply_changes_emits_structured_logs_no_secrets(
    empty_db: tuple[str, str | None], capsys: pytest.CaptureFixture[str]
) -> None:
    """Applied steps are logged as JSON lines to stdout; no secrets
    (02-non-functional: Observability)."""
    url, target_schema = empty_db
    conform = dbconform.DbConform(credentials={"url": url}, target_schema=target_schema)
    conform.apply_changes(SimpleTable)
    out, _ = capsys.readouterr()
    lines = [ln.strip() for ln in out.strip().split("\n") if ln.strip()]
    assert len(lines) >= 1
    for line in lines:
        record = json.loads(line)
        assert record.get("event") == "apply_step"
        assert "step_index" in record
        assert "description" in record
    combined = out.lower()
    assert "password" not in combined
    assert "secret" not in combined
    # URL may appear in other output; we only require no credentials in our log lines
    for line in lines:
        rec = json.loads(line)
        assert "url" not in rec
        assert "credentials" not in rec


def test_apply_changes_log_file_written(empty_db: tuple[str, str | None], tmp_path: Path) -> None:
    """Optional log_file receives same structured log lines
    (02-non-functional: optional log file)."""
    url, target_schema = empty_db
    log_path = tmp_path / "dbconform.log"
    conform = dbconform.DbConform(credentials={"url": url}, target_schema=target_schema)
    conform.apply_changes(SimpleTable, log_file=str(log_path))
    assert log_path.exists()
    content = log_path.read_text()
    lines = [ln.strip() for ln in content.strip().split("\n") if ln.strip()]
    assert len(lines) >= 1
    assert json.loads(lines[0]).get("event") == "apply_step"


def test_apply_changes_invalid_url_returns_conform_error() -> None:
    """Invalid or unreachable DB URL yields ConformError with target_objects
    (01-functional: Error handling)."""
    conform = dbconform.DbConform(
        credentials={"url": "postgresql://localhost:19999/nonexistent_db"},
        target_schema="public",
    )
    result = conform.apply_changes(SimpleTable)
    assert isinstance(result, dbconform.ConformError)
    assert len(result.messages) >= 1
    assert len(result.target_objects) >= 1


def test_compare_empty_model_list_returns_empty_plan(
    empty_db: tuple[str, str | None],
) -> None:
    """compare([]) returns a plan with no steps and no extra_tables (empty model list)."""
    url, target_schema = empty_db
    conform = dbconform.DbConform(credentials={"url": url}, target_schema=target_schema)
    plan_or_err = conform.compare([])
    assert not isinstance(plan_or_err, dbconform.ConformError)
    assert len(plan_or_err.steps) == 0
    assert len(plan_or_err.extra_tables) == 0


def test_missing_index_apply_changes_creates_index(
    empty_db: tuple[str, str | None],
) -> None:
    """Model has index on column; DB has table but no index. Plan has CREATE INDEX;
    apply_changes applies (01-functional: add/remove indexes)."""
    url, target_schema = empty_db
    conform = dbconform.DbConform(credentials={"url": url}, target_schema=target_schema)
    conform.apply_changes(SimpleTableWithIndex)
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(text('DROP INDEX IF EXISTS "idx_simple_table_with_index_name"'))
        conn.commit()
    engine.dispose()

    conform = dbconform.DbConform(credentials={"url": url}, target_schema=target_schema)
    plan_or_err = conform.compare(SimpleTableWithIndex)
    assert not isinstance(plan_or_err, dbconform.ConformError)
    assert len(plan_or_err.steps) == 1
    assert "CREATE INDEX" in (plan_or_err.steps[0].sql or "")
    assert "idx_simple_table_with_index_name" in (plan_or_err.steps[0].sql or "")

    result = conform.apply_changes(SimpleTableWithIndex)
    assert not isinstance(result, dbconform.ConformError)
    recompare = conform.compare(SimpleTableWithIndex)
    assert not isinstance(recompare, dbconform.ConformError)
    assert len(recompare.steps) == 0
