# SQLite vs PostgreSQL: differences and impact on dbconform

**When you add or change SQLite-specific behavior, add or update the relevant section here.** See [.cursor/rules/sqlite-dialect.mdc](../../.cursor/rules/sqlite-dialect.mdc).

This document describes how SQLite differs from PostgreSQL in ways that affect dbconform, what downstream effects we see, and how we handle them.

---

## 1. ALTER TABLE: adding constraints

**Difference:** SQLite does not support `ALTER TABLE ADD CONSTRAINT` for CHECK, UNIQUE, or FOREIGN KEY. PostgreSQL does.

**Impact on dbconform:** For SQLite, we cannot add these constraints in place. Instead, we must rebuild the table: create a new table with the target schema, copy data, drop the old table, rename the new one.

**Mitigation:** `RebuildTableStep` in `src/dbconform/sql_dialect/sqlite_rebuild.py`. Config flag `allow_sqlite_table_rebuild` (default: True) enables it; when False, steps are skipped and drift may remain.

---

## 2. Index names are database-global

**Difference:** In SQLite, index names are unique across the entire database, not per-table. PostgreSQL allows the same index name on different tables.

**Impact on dbconform:** During a table rebuild, we create `tablename_dbconform_new` and copy data. If we create indexes on the new table before dropping the old one, index names collide (e.g. `ix_foo` on old and new table at the same time).

**Mitigation:** Create indexes only *after* DROP TABLE and RENAME. The old table and its indexes are gone, so original index names can be used on the renamed table.

---

## 3. CHECK expressions: table-qualified column references

**Difference:** When creating a table, CHECK constraints must reference columns of the table being created. Model-derived CHECKs often use `tablename.column` (e.g. `execution_lanes.concurrency_mode`). For `CREATE TABLE tablename_dbconform_new`, that qualifier is wrong—the new table has different column context.

**Impact on dbconform:** DDL for the new table would reference nonexistent or wrong columns, causing syntax or scope errors.

**Mitigation:** `_rewrite_check_expressions_for_new_table()` in `sqlite_rebuild.py` strips table qualifiers from CHECK expressions so they use unqualified column names (e.g. `concurrency_mode` instead of `execution_lanes.concurrency_mode`).

---

## 4. Default value functions

**Difference:** SQLite DEFAULT accepts only `CURRENT_TIMESTAMP`, `CURRENT_DATE`, `CURRENT_TIME`—no function calls like `now()`. PostgreSQL supports `now()`, `localtimestamp`, etc.

**Impact on dbconform:** Models using `func.now()` or `localtimestamp` produce DDL that SQLite rejects.

**Mitigation:** `SQLiteDialect.default_for_ddl()` maps `now()`, `localtimestamp`, `localtimestamp()` to `CURRENT_TIMESTAMP`.

---

## 5. Column type changes and shrinking

**Difference:** SQLite has very limited `ALTER TABLE` support. It cannot change column types or shrink column length in place. PostgreSQL can `ALTER COLUMN ... TYPE ...`.

**Impact on dbconform:** For SQLite, we do not emit ALTER steps for type changes or length shrinks; the plan would contain no step for these diffs. Shrinking (e.g. `VARCHAR(500)` → `VARCHAR(255)`) risks data truncation.

**Mitigation:** `allow_shrink_column` (default: False) gates shrink alters; even on PostgreSQL it is opt-in. For SQLite, type/length alters are never applied; drift may remain unless a full rebuild is triggered for other reasons.

---

## 6. Memory URL sharing (async)

**Difference:** `sqlite:///:memory:` creates a new in-memory DB per connection. For async (`sqlite+aiosqlite:///:memory:`), connections must share the same DB to see each other's schema.

**Impact on dbconform:** Async compare/apply/connection workflows would use different in-memory DBs if the URL is passed through unmodified.

**Mitigation:** `_ensure_sqlite_memory_shared()` rewrites `:memory:` to `file:dbconform_mem?mode=memory&cache=shared` so connections share one in-memory instance.

---

## 7. Schemas

**Difference:** SQLite has no schema concept (no `CREATE SCHEMA`, no `schema.table`). PostgreSQL supports schemas and `target_schema` for filtering.

**Impact on dbconform:** `target_schema` is ignored for SQLite. Schema-qualified table names in SQLite DDL are not used.

---

## Summary of SQLite-related flags

| Flag                         | Default | Purpose                                                                 |
|-----------------------------|---------|-------------------------------------------------------------------------|
| `allow_sqlite_table_rebuild` | True    | Rebuild tables to add CHECK/UNIQUE/FK when SQLite cannot ALTER in place |
| `allow_shrink_column`       | False   | Allow ALTER to shrink column length (PostgreSQL only; SQLite never alters type/length) |

---

## Related code

- `src/dbconform/sql_dialect/sqlite.py` — SQLite dialect (CREATE TABLE, defaults, identifiers)
- `src/dbconform/sql_dialect/sqlite_rebuild.py` — table rebuild logic
- `src/dbconform/plan/builder.py` — plan steps, SQLite-specific rebuild/skip logic
