# Test organization

Tests are split by kind:

| Directory | Purpose |
|-----------|--------|
| **`unit/`** | Unit tests: no real database. They use mocks, in-memory structures, or the dialect/plan/schema logic only. Fast and isolated. |
| **`integration/`** | Integration tests: use a real database via `empty_sqlite_db` (SQLite) or `empty_db` (parametrized: SQLite + PostgreSQL). They exercise ModelSync against actual tables. |

## Running tests

**Recommended:** Use the **modelsync test CLI** so you get clear feedback when Postgres is unavailable (exit code 2 and a message) instead of silent skips. See `docs/technical/01-test-database.md` for full Test CLI and Postgres setup.

- **Run all tests:** `modelsync test run` — exit 0 (pass), 1 (test failure), or 2 (Postgres not available; run `modelsync test check-container`, then `modelsync test postgres up`, set `MODELSYNC_TEST_POSTGRES_URL` as printed, then run again).
- **Verify Docker/Podman and image:** `modelsync test check-container` — creates and removes a short-lived Postgres container; exit 1 with a clear reason if runtime or image fails.
- **Start Postgres for tests:** `modelsync test postgres up` — prints the URL to set; then `modelsync test run`.
- **Stop Postgres:** `modelsync test postgres down`.

Set `MODELSYNC_CONTAINER_CMD=docker` or `podman` if the binary is not on PATH. Install the dev extra for the CLI: `uv sync --extra dev` (or `pip install -e ".[dev]"`).

**Direct pytest** (alternative):

- **All:** `pytest tests/`
- **Unit only:** `pytest tests/unit/`
- **Integration only:** `pytest tests/integration/`
- **PostgreSQL integration tests** require the optional `postgres` extra: `uv sync --all-extras` or `pip install -e ".[postgres]"`. Set **`MODELSYNC_TEST_POSTGRES_URL`** (e.g. from `modelsync test postgres up` or an existing server). If the URL is not set, Postgres runs are skipped.

## Troubleshooting PostgreSQL skips

If you see many tests **skipped** (e.g. 22), those are the `[postgres]` parametrized runs. To see why they were skipped:

1. **Show skip reasons:**  
   `pytest tests/integration/ -v -rs`  
   The `-rs` option prints a skip summary at the end; each line includes the skip message. The message now includes **Reason: ...** with the underlying error (e.g. MODELSYNC_TEST_POSTGRES_URL not set). Running a single Postgres test is often clearer:  
   `pytest tests/integration/test_compare_simple_model.py::test_compare_empty_db_returns_create_step[postgres] -v`  
   You’ll see either the real failure (traceback) or a skip with the reason.

2. **Enable Postgres:**  
   - Start a PostgreSQL instance (e.g. `modelsync test postgres up`, or local install, or `docker run -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16`).  
   - Export the URL (use the `postgres` database for the fixture to create/drop test DBs):  
     `export MODELSYNC_TEST_POSTGRES_URL="postgresql://postgres:postgres@localhost:5432/postgres"`  
   - Run tests again; the `[postgres]` runs should execute.

## Shared test data

- **`shared_models.py`** — SQLModel classes (e.g. `SimpleTable`) used by both unit and integration tests. Not collected as tests by pytest.

## Fixtures

- **`integration/conftest.py`** — Defines `empty_sqlite_db` (fresh SQLite file per test under `tmp_path`), `empty_postgres_db` (PostgreSQL: env URL only, per-test DB), and `empty_db` (parametrized over sqlite/postgres for identical tests). See `docs/technical/01-test-database.md` for strategy.

## Additional test ideas (not yet implemented)

- **Apply failure / rollback**: Run do_sync with a plan that includes invalid SQL; assert SyncError and that the DB is unchanged (transaction rolled back).
- **Unique / index / check constraints**: Add a model with unique constraint or index; integration test that missing constraint in DB yields a step and do_sync applies it.
- **Diff: removed_columns, modified_columns**: Unit tests for SchemaDiffer when DB has extra columns or type/length differences (beyond the single modified_table added_columns case).
