# Functional requirements

## Feature list
- Compare code models to a live database and compute DDL and data operations to achieve schema parity.
- Dry-run by default; apply only after explicit confirmation or apply flag. Option to output DDL and data operations only (for manual execution).
- Add/alter only by default; drops require explicit opt-in.

## User / API flows

### Model discovery and API
- dbconform does **not** discover or parse Python files on its own. Callers write their own models and **import dbconform** into their code, then call library APIs and pass models explicitly.
- **Supported model frameworks:** SQLAlchemy, SQLModel, Django Models, Tortoise ORM, Piccolo ORM. Support for frameworks other than SQLAlchemy/SQLModel may be provided via adapters that produce the same internal schema used for comparison.
- The API must accept either a single model or a sequence of models (e.g. to functions such as `compare()` or `apply_changes()`).

### Database connection
- The library must provide API interfaces for callers to either:
  - **Pass an existing DB connection** (that they created), or
  - **Pass credentials** so that dbconform creates and uses the connection.
- When the caller passes **credentials** (not a connection), dbconform **opens** the connection, runs the conform, and **closes** the connection. The caller does not manage connection lifecycle in that case.
- **SQLite :memory:** When credentials use a SQLite in-memory URL (`:memory:`), dbconform rewrites it to use shared cache (`?cache=shared`) so multiple `compare()` or `apply_changes()` calls share one logical database instead of each creating a fresh empty DB.
- **Sync and async:** `DbConform` accepts sync `Connection` (or credentials with sync URLs like `sqlite:///`, `postgresql+psycopg://`). `AsyncDbConform` accepts async `AsyncConnection` (or credentials with async URLs like `sqlite+aiosqlite:///`, `postgresql+asyncpg://`). Sync URLs must not be passed to `AsyncDbConform`; async URLs must not be passed to `DbConform`.

### Target schema
- For databases that support schemas (e.g. PostgreSQL), the **target schema** must be supplied by the caller and is a **mandatory** argument at dbconform instantiation (or equivalent API entry point). The caller is responsible for specifying which schema to conform. For databases that do not have schemas (e.g. SQLite), the target-schema argument may be omitted or ignored.

### CLI scope
- In Phase 1, the **CLI is primarily for running tests** (and possibly that alone). The main use of dbconform is as a library: callers import it and invoke the API with their models and connection/credentials.
- **Test CLI** (`dbconform test`): Commands for the test workflow (check-container, postgres up/down, test run). Exit 2 when Postgres is unavailable. See [01-test-database.md](../technical/01-test-database.md) for commands and exit codes.
- **Suggestion**: A minimal conform CLI (e.g. one command that accepts a model module and DB URL and runs compare/conform) could be added later for ad-hoc runs or CI without writing Python; this is optional and not required for Phase 1.

### Program flow and confirmation
- **API**: No execution unless the caller uses apply. The library exposes **compare(models)** (dry-run: returns a plan only) and **apply_changes(models)** (compare then apply the plan in one transaction). So dry-run is the default when using compare(); apply happens only when the caller invokes apply_changes(). The library returns a plan (DDL and data-operation steps) for inspection or for the caller to execute elsewhere. Output-only mode is available by using compare() and emitting plan SQL (e.g. plan.sql()) to stdout or file.
- **CLI** (when a conform CLI is provided): Same semantics—dry-run by default; user prompted to confirm (e.g. "Apply these changes? [y/N]") before execution.
- **Destructive changes**: By default only add/alter; drops and other destructive changes require explicit opt-in from the caller (or user, when using CLI).
- **Opt-in flags**: The API exposes five boolean flags on `compare()` and `apply_changes()`:
  - **allow_drop_extra_tables**: when True, the plan may include DROP TABLE steps for tables present in the DB but not in the model. Default false.
  - **allow_drop_extra_columns**: when True, the plan may include DROP COLUMN steps for columns present in the DB but not in the model. Default false.
  - **allow_drop_extra_constraints**: when True (default), the plan may include DROP CONSTRAINT / DROP INDEX steps for unique, foreign key, check, or index objects removed from the model. Default True (no data loss, easily reversible).
  - **allow_shrink_column**: when True, the plan may include ALTER COLUMN steps that shrink a column (e.g. reduce VARCHAR length); when False (default), such changes are omitted to avoid data-loss risk unless the caller opts in.
  - **allow_sqlite_table_rebuild**: when True (default), SQLite tables missing CHECK, UNIQUE, or FOREIGN KEY constraints are rebuilt (create new table with constraints, copy data, drop old, rename) to achieve parity. When False, such constraint adds are skipped and recorded in `plan.skipped_steps`; drift remains and is logged clearly.

### Transaction behavior
- Transaction behavior is **configurable**. **Default:** all-or-nothing—if any step fails during apply, the entire conform is rolled back. **Option:** `commit_per_step=True` on `apply_changes()` commits after each step so that prior steps persist if a later step fails.
- **Transaction-awareness**: When the connection is already in a transaction (e.g. from `engine.begin()` or after compare via `engine.connect()`), dbconform uses a savepoint for the apply block instead of a new transaction. Both `engine.connect()` and `engine.begin()` are supported. See [docs/technical/03-transactions-and-savepoints.md](../technical/03-transactions-and-savepoints.md).

### Plan and DDL order
- DDL and data-operation steps must be produced in a **valid execution order**: dependencies must be respected (e.g. create table before creating a foreign key that references it). Documentation and implementation must reflect this.
- The compare/apply flow returns a `ConformPlan` object with three main elements: `steps` (ordered DDL/data operations), `extra_tables` (tables present only in the DB), and `skipped_steps` (differences intentionally not applied due to safety flags or backend limits). `ConformPlan.summary()` / `print_summary()` provide a human-readable summary of these elements for ad‑hoc inspection.

### Error handling
- When conform or compare fails, the API returns a **structured Error object** to the caller (not only an exception or string). The structure must allow the caller to determine **which target objects** did not conform and **why**, so that callers can handle or report failures precisely.

### Schema parity scope
Elements that dbconform compares and corrects (add/alter as per default behavior):
- **Tables** (create missing; drop only if explicitly opted in).
- **Columns** (add missing; alter type, nullability, defaults).
- **Primary keys**, **unique constraints**, **foreign keys**, **indexes**, **check constraints**.
- **Table and column comments** (where supported by the backend).

**SQLite constraint rebuild:** SQLite does not support `ALTER TABLE ADD CONSTRAINT` for CHECK, UNIQUE, or FOREIGN KEY. By default (`allow_sqlite_table_rebuild=True`), dbconform rebuilds the table (create new with constraints, copy data, drop old, rename) to achieve full parity. Set `allow_sqlite_table_rebuild=False` to skip rebuilds; skipped steps are recorded in `plan.skipped_steps` and emitted as structured logs (`event: skipped_step`) so the user sees that drift remains.

**Identifiers and quoting:** Table and column names follow the **target database’s quoting rules** (e.g. PostgreSQL double quotes, MariaDB backticks). dbconform does not impose a separate quoting scheme.

**Future phase (may be added later):** sequences, triggers, enums.

### Data operations
- **Backfilling**: When new columns are added, dbconform can backfill them with default or constant values where applicable.
- **Type changes**: When column types are altered, existing data may be transformed to match the new type.
- **Adding NOT NULL to a column that contains NULLs**: If the model defines a **default** for that column, dbconform applies it (backfill) so the column can be made NOT NULL. If the model has **no default**, dbconform **errors** and requires the caller to backfill the NULLs themselves before retrying conform.
- **Data-loss risk**: When a change may cause data loss (e.g. reducing the length of a string field), dbconform does not emit the ALTER step unless the caller sets **allow_shrink_column** (e.g. `compare(..., allow_shrink_column=True)`). Default is false so shrinking a column requires explicit opt-in. When a shrink is skipped, the would-be ALTER is recorded in `plan.skipped_steps` and exposed via `skipped_step` logs so callers can see that drift remains and decide whether to re-run with `allow_shrink_column=True`.

### Column rename (future phase — Phase 2)
- **Goal**: Support indicating that a column was renamed in the model (e.g. `bar` → `baz` on table `foo`). Some databases support `RENAME COLUMN`; others require: add new column → copy data from old column → drop old column.
- **Open design**: How to indicate a rename in the model (SQLAlchemy/SQLModel) so dbconform can distinguish "new column + drop old" from "rename" and avoid treating it as two unrelated changes. This is targeted for a future phase (Phase 2).

## Acceptance criteria
Acceptance is demonstrated by unit tests: given any in-scope model, synchronization to a real SQL database must succeed. Required coverage:

- **Schema:** Create new tables; add/remove columns (remove only when opted in); alter columns (type, length, nullability, default); add/remove primary keys, unique and foreign-key constraints, indexes, check constraints.
- **Data operations:** Backfill new columns with default or constant; transform data when column type changes; when a change risks data loss (e.g. truncation), warn and require confirmation before applying.
- **Safe behavior:** Dry-run returns a plan without applying; output-only produces a correct DDL/data-operations script; without apply (or drop opt-in), no changes are applied.
- **Backends:** An identical database model/schema works correctly with SQLite, PostgreSQL, and MariaDB with dialect-appropriate DDL.
