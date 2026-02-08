"""
Integration tests: ModelSync.compare() against a real SQLite database.

Traceability: docs/requirements/01-functional.md — Model discovery and API,
Database connection, compare() / do_sync(). Acceptance: schema (create tables, columns).
"""

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

import modelsync
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


def test_compare_empty_db_returns_create_step(empty_sqlite_db: tuple[Path, str]) -> None:
    """Scenario 1: model has table, DB does not — plan contains CREATE TABLE (01-functional)."""
    _path, url = empty_sqlite_db
    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)
    result = sync.compare(SimpleTable)
    assert not isinstance(result, modelsync.SyncError), str(result)
    plan = result
    assert len(plan.steps) == 1
    assert "simple_table" in plan.sql()
    assert "CREATE TABLE" in plan.sql()


def test_compare_with_connection(empty_sqlite_db: tuple[Path, str]) -> None:
    """Caller passes connection; compare returns plan (01-functional: pass existing connection)."""
    _path, url = empty_sqlite_db
    engine = create_engine(url)
    with engine.connect() as conn:
        sync = modelsync.ModelSync(connection=conn, target_schema=None)
        result = sync.compare(SimpleTable)
    engine.dispose()
    assert not isinstance(result, modelsync.SyncError)
    assert len(result.steps) == 1


def test_do_sync_with_connection_caller_closes(empty_sqlite_db: tuple[Path, str]) -> None:
    """Caller passes connection; do_sync applies plan; caller closes connection (01-functional)."""
    _path, url = empty_sqlite_db
    engine = create_engine(url)
    with engine.connect() as conn:
        sync = modelsync.ModelSync(connection=conn, target_schema=None)
        result = sync.do_sync(SimpleTable)
    engine.dispose()
    assert not isinstance(result, modelsync.SyncError), str(result)
    assert len(result.steps) == 1
    # Reopen and recompare to confirm schema parity
    engine2 = create_engine(url)
    with engine2.connect() as conn2:
        sync2 = modelsync.ModelSync(connection=conn2, target_schema=None)
        recompare = sync2.compare(SimpleTable)
    engine2.dispose()
    assert not isinstance(recompare, modelsync.SyncError)
    assert len(recompare.steps) == 0


def test_compare_after_create_same_schema_no_steps(empty_sqlite_db: tuple[Path, str]) -> None:
    """Scenario 3: table exists in DB and matches model — no steps (schema parity)."""
    _path, url = empty_sqlite_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE simple_table "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(255) NOT NULL, "
                "value FLOAT NOT NULL, count INTEGER NOT NULL)"
            )
        )
        conn.commit()
    with engine.connect() as conn:
        sync = modelsync.ModelSync(connection=conn, target_schema=None)
        result = sync.compare(SimpleTable)
    engine.dispose()
    assert not isinstance(result, modelsync.SyncError)
    assert len(result.steps) == 0


def test_compare_extra_table_in_db_reported_not_dropped(empty_sqlite_db: tuple[Path, str]) -> None:
    """Scenario 2: DB has table not in model — reported in extra_tables, no DROP (01-functional)."""
    _path, url = empty_sqlite_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE other_table (id INTEGER PRIMARY KEY)"))
        conn.commit()
    with engine.connect() as conn:
        sync = modelsync.ModelSync(connection=conn, target_schema=None)
        result = sync.compare(SimpleTable)
    engine.dispose()
    assert not isinstance(result, modelsync.SyncError)
    assert len(result.extra_tables) == 1
    assert result.extra_tables[0].name == "other_table"
    assert not any("DROP" in (s.sql or "") for s in result.steps)


def test_do_sync_applies_plan_then_recompare_parity(empty_sqlite_db: tuple[Path, str]) -> None:
    """Table missing; do_sync applies CREATE; recompare yields 0 steps (01-functional)."""
    _path, url = empty_sqlite_db
    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)
    result = sync.do_sync(SimpleTable)
    assert not isinstance(result, modelsync.SyncError), str(result)
    plan = result
    assert len(plan.steps) == 1
    assert "CREATE TABLE" in plan.sql()
    recompare = sync.compare(SimpleTable)
    assert not isinstance(recompare, modelsync.SyncError)
    assert len(recompare.steps) == 0


def test_compare_invalid_model_returns_sync_error(empty_sqlite_db: tuple[Path, str]) -> None:
    """Passing a class with no __table__ returns SyncError (01-functional: Error handling)."""
    _path, url = empty_sqlite_db
    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)

    class NotATable:
        """Plain class; no __table__, not a mapped model."""

    result = sync.compare(NotATable)
    assert isinstance(result, modelsync.SyncError)
    assert len(result.messages) >= 1
    assert len(result.target_objects) >= 1, "SyncError must identify which target failed (01-functional: Error handling)"


def test_do_sync_apply_failure_returns_sync_error_with_target_objects(
    empty_sqlite_db: tuple[Path, str],
) -> None:
    """When a plan step fails during apply (e.g. unsupported SQL on SQLite), do_sync returns SyncError with target_objects (01-functional: Error handling)."""
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

    # SimpleTableWithUnique adds UNIQUE(name); SQLite does not support ALTER TABLE ADD CONSTRAINT, so apply fails.
    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)
    result = sync.do_sync(SimpleTableWithUnique)
    assert isinstance(result, modelsync.SyncError)
    assert len(result.messages) >= 1
    assert len(result.target_objects) >= 1
    assert any(
        obj[0] == "table" or obj[0] == "step" for obj in result.target_objects
    )


def test_do_sync_commit_per_step_succeeds(empty_sqlite_db: tuple[Path, str]) -> None:
    """do_sync(..., commit_per_step=True) applies plan and commits after each step (01-functional: Transaction behavior)."""
    _path, url = empty_sqlite_db
    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)
    result = sync.do_sync(SimpleTable, commit_per_step=True)
    assert not isinstance(result, modelsync.SyncError)
    recompare = sync.compare(SimpleTable)
    assert not isinstance(recompare, modelsync.SyncError)
    assert len(recompare.steps) == 0


def test_do_sync_emits_structured_logs_no_secrets(
    empty_sqlite_db: tuple[Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    """Applied steps are logged as JSON lines to stdout; no secrets (02-non-functional: Observability)."""
    _path, url = empty_sqlite_db
    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)
    sync.do_sync(SimpleTable)
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


def test_do_sync_log_file_written(empty_sqlite_db: tuple[Path, str], tmp_path: Path) -> None:
    """Optional log_file receives same structured log lines (02-non-functional: optional log file)."""
    _path, url = empty_sqlite_db
    log_path = tmp_path / "modelsync.log"
    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)
    sync.do_sync(SimpleTable, log_file=str(log_path))
    assert log_path.exists()
    content = log_path.read_text()
    lines = [ln.strip() for ln in content.strip().split("\n") if ln.strip()]
    assert len(lines) >= 1
    assert json.loads(lines[0]).get("event") == "apply_step"


def test_do_sync_invalid_url_returns_sync_error() -> None:
    """Invalid or unreachable DB URL yields SyncError with target_objects (01-functional: Error handling)."""
    sync = modelsync.ModelSync(
        credentials={"url": "postgresql://localhost:19999/nonexistent_db"},
        target_schema="public",
    )
    result = sync.do_sync(SimpleTable)
    assert isinstance(result, modelsync.SyncError)
    assert len(result.messages) >= 1
    assert len(result.target_objects) >= 1


def test_compare_empty_model_list_returns_empty_plan(
    empty_sqlite_db: tuple[Path, str],
) -> None:
    """compare([]) returns a plan with no steps and no extra_tables (empty model list)."""
    _path, url = empty_sqlite_db
    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)
    plan_or_err = sync.compare([])
    assert not isinstance(plan_or_err, modelsync.SyncError)
    assert len(plan_or_err.steps) == 0
    assert len(plan_or_err.extra_tables) == 0


def test_missing_index_do_sync_creates_index(
    empty_sqlite_db: tuple[Path, str],
) -> None:
    """Model has index on column; DB has table but no index. Plan has CREATE INDEX; do_sync applies (01-functional: add/remove indexes)."""
    _path, url = empty_sqlite_db
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE simple_table_with_index ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(255) NOT NULL, "
                "value FLOAT NOT NULL, count INTEGER NOT NULL)"
            )
        )
        conn.commit()
    engine.dispose()

    sync = modelsync.ModelSync(credentials={"url": url}, target_schema=None)
    plan_or_err = sync.compare(SimpleTableWithIndex)
    assert not isinstance(plan_or_err, modelsync.SyncError)
    assert len(plan_or_err.steps) == 1
    assert "CREATE INDEX" in (plan_or_err.steps[0].sql or "")
    assert "idx_simple_table_with_index_name" in (plan_or_err.steps[0].sql or "")

    result = sync.do_sync(SimpleTableWithIndex)
    assert not isinstance(result, modelsync.SyncError)
    recompare = sync.compare(SimpleTableWithIndex)
    assert not isinstance(recompare, modelsync.SyncError)
    assert len(recompare.steps) == 0
