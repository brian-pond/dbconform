# Test organization

Tests are split by kind:

| Directory | Purpose |
|-----------|--------|
| **`unit/`** | Unit tests: no real database. They use mocks, in-memory structures, or the dialect/plan/schema logic only. Fast and isolated. |
| **`integration/`** | Integration tests: use a real SQLite database (via the `empty_sqlite_db` fixture). They exercise ModelSync against actual tables. |

## Running tests

- **All:** `pytest tests/`
- **Unit only:** `pytest tests/unit/`
- **Integration only:** `pytest tests/integration/`

## Shared test data

- **`shared_models.py`** — SQLModel classes (e.g. `SimpleTable`) used by both unit and integration tests. Not collected as tests by pytest.

## Fixtures

- **`integration/conftest.py`** — Defines `empty_sqlite_db`: a fresh SQLite file under `tmp_path` per test. See `docs/technical/01-test-database.md` for strategy.

## Additional test ideas (not yet implemented)

- **Apply failure / rollback**: Run do_sync with a plan that includes invalid SQL; assert SyncError and that the DB is unchanged (transaction rolled back).
- **Unique / index / check constraints**: Add a model with unique constraint or index; integration test that missing constraint in DB yields a step and do_sync applies it.
- **Invalid DB URL**: compare() or do_sync() with a bad URL returns SyncError (connection failure path).
- **Empty model list**: compare([]) or compare with empty sequence — document or test expected behavior.
- **Diff: removed_columns, modified_columns**: Unit tests for SchemaDiffer when DB has extra columns or type/length differences (beyond the single modified_table added_columns case).
