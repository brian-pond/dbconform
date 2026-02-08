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

- **`shared_models.py`** — SQLModel classes (e.g. `SimpleRecord`) used by both unit and integration tests. Not collected as tests by pytest.

## Fixtures

- **`integration/conftest.py`** — Defines `empty_sqlite_db`: a fresh SQLite file under `tmp_path` per test. See `docs/technical/01-test-database.md` for strategy.
