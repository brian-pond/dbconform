# Functional requirements

## Feature list
- Compare code models to a live database and compute DDL and data operations to achieve schema parity.
- Dry-run by default; apply only after explicit confirmation or apply flag. Option to output DDL and data operations only (for manual execution).
- Add/alter only by default; drops require explicit opt-in.

## User / API flows

### Model discovery and API
- modelsync does **not** discover or parse Python files on its own. Callers write their own models (SQLAlchemy or SQLModel) and **import modelsync** into their code, then call library APIs and pass models explicitly.
- The API must accept either a single model or a sequence of models (e.g. to functions such as `compare()` or `do_sync()`).

### Database connection
- The library must provide API interfaces for callers to either:
  - **Pass an existing DB connection** (that they created), or
  - **Pass credentials** so that modelsync creates and uses the connection.
- When the caller passes **credentials** (not a connection), modelsync **opens** the connection, runs the sync, and **closes** the connection. The caller does not manage connection lifecycle in that case.

### Target schema
- For databases that support schemas (e.g. PostgreSQL), the **target schema** must be supplied by the caller and is a **mandatory** argument at modelsync instantiation (or equivalent API entry point). The caller is responsible for specifying which schema to sync. For databases that do not have schemas (e.g. SQLite), the target-schema argument may be omitted or ignored.

### CLI scope
- In Phase 1, the **CLI is primarily for running tests** (and possibly that alone). The main use of modelsync is as a library: callers import it and invoke the API with their models and connection/credentials.
- **Suggestion**: A minimal sync CLI (e.g. one command that accepts a model module and DB URL and runs compare/sync) could be added later for ad-hoc runs or CI without writing Python; this is optional and not required for Phase 1.

### Sync flow and confirmation
- **API**: No execution unless the caller passes an explicit apply option (default: false). The library returns a plan (DDL and data-operation steps) for inspection or for the caller to execute elsewhere. Output-only mode must be available: emit planned DDL and data operations to stdout or file with no apply and no prompt.
- **CLI** (when a sync CLI is provided): Same semantics—dry-run by default; user prompted to confirm (e.g. "Apply these changes? [y/N]") before execution.
- **Destructive changes**: By default only add/alter; drops and other destructive changes require explicit opt-in from the caller (or user, when using CLI).

### Transaction behavior
- Transaction behavior is **configurable**. **Default:** all-or-nothing—if any step fails during apply, the entire sync is rolled back. Alternative behavior (e.g. commit per step) may be offered as an option when supported.

### Plan and DDL order
- DDL and data-operation steps must be produced in a **valid execution order**: dependencies must be respected (e.g. create table before creating a foreign key that references it). Documentation and implementation must reflect this.

### Error handling
- When sync or compare fails, the API returns a **structured Error object** to the caller (not only an exception or string). The structure must allow the caller to determine **which target objects** did not sync and **why**, so that callers can handle or report failures precisely.

### Schema parity scope
Elements that modelsync compares and corrects (add/alter as per default behavior):
- **Tables** (create missing; drop only if explicitly opted in).
- **Columns** (add missing; alter type, nullability, defaults).
- **Primary keys**, **unique constraints**, **foreign keys**, **indexes**, **check constraints**.
- **Table and column comments** (where supported by the backend).

**Identifiers and quoting:** Table and column names follow the **target database’s quoting rules** (e.g. PostgreSQL double quotes, MariaDB backticks). modelsync does not impose a separate quoting scheme.

**Future phase (may be added later):** sequences, triggers, enums.

### Data operations
- **Backfilling**: When new columns are added, modelsync can backfill them with default or constant values where applicable.
- **Type changes**: When column types are altered, existing data may be transformed to match the new type.
- **Adding NOT NULL to a column that contains NULLs**: If the model defines a **default** for that column, modelsync applies it (backfill) so the column can be made NOT NULL. If the model has **no default**, modelsync **errors** and requires the caller to backfill the NULLs themselves before retrying sync.
- **Data-loss risk**: When a change may cause data loss (e.g. reducing the length of a string field and truncation), modelsync must warn and require explicit confirmation before applying.

### Column rename (future phase — Phase 2)
- **Goal**: Support indicating that a column was renamed in the model (e.g. `bar` → `baz` on table `foo`). Some databases support `RENAME COLUMN`; others require: add new column → copy data from old column → drop old column.
- **Open design**: How to indicate a rename in the model (SQLAlchemy/SQLModel) so modelsync can distinguish "new column + drop old" from "rename" and avoid treating it as two unrelated changes. This is targeted for a future phase (Phase 2).

## Acceptance criteria
Acceptance is demonstrated by unit tests: given any in-scope model, synchronization to a real SQL database must succeed. Required coverage:

- **Schema:** Create new tables; add/remove columns (remove only when opted in); alter columns (type, length, nullability, default); add/remove primary keys, unique and foreign-key constraints, indexes, check constraints.
- **Data operations:** Backfill new columns with default or constant; transform data when column type changes; when a change risks data loss (e.g. truncation), warn and require confirmation before applying.
- **Safe behavior:** Dry-run returns a plan without applying; output-only produces a correct DDL/data-operations script; without apply (or drop opt-in), no changes are applied.
- **Backends:** Same model syncs correctly to SQLite, PostgreSQL, and MariaDB with dialect-appropriate DDL.
