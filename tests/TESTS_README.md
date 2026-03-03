# Test organization

Tests are split by kind and, for unit tests, aligned with the **four core functions** in [docs/technical/02-architecture.md](../docs/technical/02-architecture.md):

| Directory | Purpose |
|-----------|--------|
| **`unit/`** | Unit tests: no real database. Layout mirrors architecture: **internal** (schema types), **adapters** (model → internal), **compare** (diff), **plan**, **sql_dialect** (DDL). Fast and isolated. |
| **`integration/`** | Integration tests: use a real database via `empty_sqlite_db` (SQLite) or `empty_db` (parametrized: SQLite + PostgreSQL). They exercise DbConform against actual tables. |

## Unit test layout (by core function)

| `unit/` subdir | Core function | Contents |
|----------------|---------------|----------|
| **`internal/`** | Internal schema | Neutral type names and helpers (`test_types.py`). |
| **`adapters/`** | Adapters (ingest) | Model → internal: `ModelSchema`, `sa_column_to_neutral_type`, simple model sanity. |
| **`compare/`** | Compare | SchemaDiffer, `differences()`, added/removed/modified tables. |
| **`plan/`** | DDL generation (plan) | ConformPlanBuilder, step ordering, drop/shrink options. |
| **`sql_dialect/`** | DDL generation (dialect) | Dialect-specific DDL (e.g. PostgreSQL serial, quoting). |

## Running tests

**Recommended:** Use the **dbconform test CLI**. See `docs/technical/01-test-database.md` for full Test CLI and Postgres setup.

- **Run all tests:** `dbconform test run` — With [postgres] extra and Docker/Podman: auto-starts Postgres, runs full suite, stops container. Without: runs SQLite tests only. Exit 0 (pass) or 1 (failure).
- **Verify Docker/Podman and image:** `dbconform test check-container` — creates and removes a short-lived Postgres container; exit 1 with a clear reason if runtime or image fails.
- **Manual Postgres lifecycle:** `dbconform test postgres up` / `dbconform test postgres down` — start or stop the long-lived container when you want it to persist across runs.

Set `DBCONFORM_CONTAINER_CMD=docker` or `podman` if the binary is not on PATH. Install the dev extra for the CLI: `uv conform --extra dev` (or `pip install -e ".[dev]"`).

**Direct pytest** (alternative):

- **All:** `pytest tests/`
- **Unit only:** `pytest tests/unit/`
- **Integration only:** `pytest tests/integration/`
- **PostgreSQL integration tests** require the optional `postgres` extra: `uv conform --all-extras` or `pip install -e ".[postgres]"`. Set **`DBCONFORM_TEST_POSTGRES_URL`** (e.g. from `dbconform test postgres up` or an existing server). If the URL is not set, Postgres runs are skipped.

## Troubleshooting PostgreSQL skips

If you see many tests **skipped** (e.g. 22), those are the `[postgres]` parametrized runs. To see why they were skipped:

1. **Show skip reasons:**  
   `pytest tests/integration/ -v -rs`  
   The `-rs` option prints a skip summary at the end; each line includes the skip message. The message now includes **Reason: ...** with the underlying error (e.g. DBCONFORM_TEST_POSTGRES_URL not set). Running a single Postgres test is often clearer:  
   `pytest tests/integration/test_compare_simple_model.py::test_compare_empty_db_returns_create_step[postgres] -v`  
   You’ll see either the real failure (traceback) or a skip with the reason.

2. **Enable Postgres:**  
   - Start a PostgreSQL instance (e.g. `dbconform test postgres up`, or local install, or `docker run -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16`).  
   - Export the URL (use the `postgres` database for the fixture to create/drop test DBs):  
     `export DBCONFORM_TEST_POSTGRES_URL="postgresql://postgres:postgres@localhost:5432/postgres"`  
   - Run tests again; the `[postgres]` runs should execute.

## Shared test data

- **`shared_models.py`** — SQLModel classes (e.g. `SimpleTable`) used by both unit and integration tests. Not collected as tests by pytest.

## Fixtures

- **`integration/conftest.py`** — Defines `empty_sqlite_db` (fresh SQLite file per test under `tmp_path`), `empty_postgres_db` (PostgreSQL: env URL only, per-test DB), and `empty_db` (parametrized over sqlite/postgres for identical tests). See `docs/technical/01-test-database.md` for strategy.

## Additional test ideas (not yet implemented)

- **Apply failure / rollback**: Run apply_changes with a plan that includes invalid SQL; assert ConformError and that the DB is unchanged (transaction rolled back).
- **Unique / index / check constraints**: Add a model with unique constraint or index; integration test that missing constraint in DB yields a step and apply_changes applies it.
- **Diff: removed_columns, modified_columns**: Unit tests for SchemaDiffer when DB has extra columns or type/length differences (beyond the single modified_table added_columns case).
