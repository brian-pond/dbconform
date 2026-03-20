# Requirements changelog

All notable changes to the requirements docs are documented here.

## [Unreleased]

### Fixed
- **Model → DDL column defaults:** Python scalars on SQLAlchemy/SQLModel columns (e.g. `Field(default=date(1970, 1, 1))` on `DATE`) were emitted as `DEFAULT 1970-01-01`, which PostgreSQL parses as integer subtraction, not a date literal, causing datatype errors. dbconform now emits proper quoted literals for common scalar types and keeps `str(default.arg)` only for SQLAlchemy `ClauseElement` args (e.g. `server_default=text(...)`). See docs/technical/05-model-column-defaults.md.

### Added
- **SQLite constraint rebuild:** SQLite cannot add CHECK, UNIQUE, or FOREIGN KEY constraints to existing tables via ALTER TABLE. dbconform now rebuilds such tables by default (create new with constraints, copy data, drop old, rename) to achieve full schema parity. Opt-out via `allow_sqlite_table_rebuild=False`; skipped steps are recorded in `plan.skipped_steps` and logged (`event: skipped_step`). See 01-functional (Schema parity scope, Opt-in flags).
- **Shrink-related skips:** When a column-length change would shrink data and `allow_shrink_column=False`, dbconform now records the would-be ALTER as an entry in `plan.skipped_steps` and emits a `"skipped_step"` log event so callers can see that drift remains and optionally re-run with `allow_shrink_column=True`. See 01-functional (Data operations, Data-loss risk) and 02-non-functional (Observability).
- **Transaction-awareness:** When the connection is already in a transaction (e.g. from `engine.begin()`), `apply_changes()` uses a savepoint for the apply block instead of calling `connection.begin()`. Both `engine.connect()` and `engine.begin()` are supported. See 01-functional (Transaction behavior).
- **SQLite :memory: shared cache:** When using credentials with `sqlite:///:memory:` or `sqlite+aiosqlite:///:memory:`, the URL is rewritten to use `?cache=shared` so multiple `compare()` / `apply_changes()` calls share one logical in-memory database. See 01-functional (Database connection).
- **Indexes on new tables:** The plan builder now emits `CreateIndexStep` for indexes on newly added tables, so one `apply_changes()` run fully syncs new tables and their indexes (previously required a second pass).
- **emit_log option:** `apply_changes()` accepts `emit_log=False` to suppress JSON-line logs to stdout. Useful when the caller manages logging. `log_file` still appends when provided. See 02-non-functional (Observability).

### Changed
- **ConformError:** Now inherits from `Exception`, allowing `raise X from conform_error` and `except ConformError`. The API still returns it as a value; `isinstance(result, ConformError)` continues to work as before.

### Added (earlier)
- **Async support:** `AsyncDbConform` for async database connections. Pass `async_connection` (SQLAlchemy `AsyncConnection`) or `credentials` with async driver URLs (`sqlite+aiosqlite://`, `postgresql+asyncpg://`). Use `await conform.compare()` and `await conform.apply_changes()`. Optional `[async]` extra provides `aiosqlite` and `asyncpg`. See 01-functional (Database connection) and README.

### Changed
- **API rename:** `do_conform()` → `apply_changes()`; clearer name for applying schema changes. Docs and tests updated.
- **Internal naming:** CLI `_run` → `_run_subprocess`; `_get_container_cmd` → `_get_container_runtime_path`; `test_run` → `run_test_suite`; conform `_step_target` → `_step_target_for_error`; compare/diff `_dict_from` → `_build_dict_by_key`, `_fk_key` → `_foreign_key_key`; spelled-out abbrevs in `_build_table_diff`.
- **Package rename modelsync → dbconform:** Package, CLI, and env vars renamed to avoid confusion with Python sync/async. `modelsync` → `dbconform`; `ModelSync` → `DbConform`; `do_sync` → `do_conform` (later renamed to `apply_changes`); `SyncPlan` → `ConformPlan`; `SyncError` → `ConformError`; `SyncPlanBuilder` → `ConformPlanBuilder`; `SyncStep` → `ConformStep`. Env vars: `MODELSYNC_*` → `DBCONFORM_*`. PyPI package name will be `dbconform`.
- **Package rename:** The `dialect` subpackage was renamed to `sql_dialect` for clarity (DDL generation for SQL backends). Update imports from `dbconform.dialect` to `dbconform.sql_dialect`. Unit tests moved from `tests/unit/dialect/` to `tests/unit/sql_dialect/`. See docs/technical/02-architecture.md (Package layout).

### Added
- **Ingestion read-only contract:** Adapters (model ingestion) are documented as read-only: we do not mutate the caller's model classes or their `__table__` / columns. See adapters/model_schema.py docstring and docs/technical/02-architecture.md. A regression test (tests/unit/adapters/test_model_schema.py) asserts that ModelSchema.from_models() does not change the passed-in model's table fingerprint.
- **Model frameworks (in-scope):** Django Models, Tortoise ORM, and Piccolo ORM added as supported model frameworks alongside SQLAlchemy and SQLModel. Support for these may be implemented via adapters that produce the same internal schema (01-functional: Model discovery and API; 00-overview: In-scope).
- **Internal schema, neutral types, data_type_name:** Terminology and implementation updates: "canonical schema" renamed to "internal schema" across docs and code; ColumnDef attribute `type_expr` renamed to `data_type_name`; dialect method `to_canonical_type_expr` renamed to `to_neutral_type`. Design goals for internal schema (lightweight, frozen/immutable, lingua franca between ORMs and DBs) documented in docs/technical/02-architecture.md. Neutral type vocabulary (Option B) to be adopted in a follow-up: model-side schema will not depend on target dialect for type strings.
- **Four core functions:** Documentation of the four core functions (internal schema, adapters/ingest, compare, DDL generation) added to docs/technical/02-architecture.md and referenced in docs/requirements/00-overview.md. Codebase refactored into subpackages `internal`, `adapters`, and `compare`; `schema` retained as a backward-compatibility re-export.

- **Test CLI**: `dbconform test` with subcommands `check-container`, `postgres up`, `postgres down`, and `run`. With [postgres] extra and Docker/Podman, `test run` auto-starts the Postgres container, runs full suite, then stops it; otherwise runs SQLite tests only. Manual `postgres up`/`down` for persistent container. See 01-functional (CLI scope) and docs/technical/01-test-database.md.
- **PostgreSQL support**: New `PostgreSQLDialect` (DDL for create/alter/drop; schema-qualified identifiers). ModelSync accepts `postgresql` engines; target_schema required. Integration tests run identically against SQLite and PostgreSQL via parametrized `empty_db` fixture; PostgreSQL uses `DBCONFORM_TEST_POSTGRES_URL` (see docs/technical/01-test-database.md). Optional extra `postgres` (psycopg).
- **01-functional / API**: ModelSync.do_sync(models) — compare then apply the plan in a single transaction; returns SyncPlan on success or SyncError on failure. compare() remains the dry-run entry point.
- **allow_drop_extra_tables**: compare() and do_sync() accept allow_drop_extra_tables=False; when True, plan may include DROP TABLE steps for tables in DB but not in model. DropTableStep and Dialect.drop_table_sql() added.
- **allow_drop_extra_columns**: compare() and do_sync() accept allow_drop_extra_columns=False; when True, plan may include DROP COLUMN steps for columns in DB but not in model. Dialect.drop_column_sql() added (SQLite 3.35+).
- **allow_drop_extra_constraints**: compare() and do_sync() accept allow_drop_extra_constraints=True (default); when True, plan may include DROP CONSTRAINT / DROP INDEX for removed unique, foreign key, check, or index. Default True (no data loss, easily reversible). Dialect drop_unique_sql, drop_foreign_key_sql, drop_check_sql, drop_index_sql added (SQLite: only drop_index_sql; constraint drops return None).
- **allow_shrink_column**: compare() and do_sync() accept allow_shrink_column=False; when True, plan may include ALTER COLUMN steps that shrink the column (e.g. reduce VARCHAR length). Dialect.would_shrink() added; default false to avoid data-loss risk without explicit opt-in.
- **Transaction behavior**: do_sync(..., commit_per_step=True) commits after each step (configurable per 01-functional).
- **Error handling**: SyncError.target_objects populated on compare or apply failure so callers can identify which target failed (01-functional: Error handling).
- **02-non-functional / Observability**: Applied steps logged as JSON lines to stdout (machine-parseable); do_sync(..., log_file=path) optionally appends to a file. No secrets in logs.
- Integration tests (table lifecycle, columns add/extra, column type/length/nullability/default) following the 7-step pattern: create table, compare, assert plan, do_sync or no-op, recompare, assert parity or expected ongoing diff. New test modules: test_integration_table_lifecycle.py, test_integration_columns.py, test_integration_column_types.py.
- Test shared models renamed to avoid "record" (row): SimpleRecord → SimpleTable, OtherRecord → OtherTable, SimpleRecordWideName → SimpleTableWideName; table names simple_table, other_table, simple_table_wide.

### Added (earlier)

- Initial requirements scaffold (00-overview, 01-functional, 02-non-functional).
- **00-overview**: Goals (single source of truth, safe by default, CI/CD and scriptable, auditability); in-scope models (SQLAlchemy, SQLModel) and DBs (SQLite, PostgreSQL, MariaDB); out-of-scope (other DBs, migration/versioning); technology stack (library-first, CLI for tests in Phase 1).
- **01-functional**: Feature list; sync flow and confirmation (CLI prompt, API apply default no, output-only); default add/alter only (no drops unless opted in); schema parity scope (tables, columns, keys, constraints, indexes, comments; future: sequences, triggers, enums); data operations (backfill, type change, data-loss warning); column rename as Phase 2; model discovery and API (no auto-discovery, pass one or many models to e.g. `compare()` / `do_sync()`); database connection (caller passes connection or credentials); CLI scope (Phase 1: primarily for running tests); acceptance criteria as unit-test scenarios.
- **02-non-functional**: Security (no secrets in logs); deployment (Linux Phase 1, PyPI/pip); observability (structured, machine-parseable logs to stdout; optional log file).

### Changed
- **Review (all docs):** Clarified and tightened wording; removed duplication; fixed typo ("is become" → "is to become"); overview tagline and single-sentence core function; in-scope as bullet list; feature list condensed; sync flow ordered API-first with CLI conditional; acceptance criteria merged into one required-coverage list; NFRs: Performance placeholder and non-functional acceptance criteria added.

### Added
- **01-functional:** Transaction behavior (configurable; default all-or-nothing, rollback on failure). Plan and DDL order (valid execution order, dependencies respected). Connection lifecycle when credentials passed (dbconform opens, runs sync, closes). Target schema mandatory for schema-supporting DBs (e.g. PostgreSQL). Error handling: structured Error object identifying which objects failed and why. NOT NULL on column with NULLs: apply default if present, else error and require caller to backfill. Identifiers and quoting: follow target database rules (e.g. PostgreSQL double quotes, MariaDB backticks).
- **02-non-functional:** Dependencies: Phase 1 support latest LTS versions of SQLAlchemy and SQLModel.
- **docs/technical/00-libraries-packages.md:** Version policy (Phase 1) referencing 02-non-functional.
- **01-functional:** Target schema: for DBs without schemas (e.g. SQLite), target-schema argument may be omitted or ignored.
- **02-non-functional:** Documentation: public API must be documented (e.g. README and API reference).
