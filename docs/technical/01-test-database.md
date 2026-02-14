# Test database strategy

How we provide real SQL databases for tests without polluting the filesystem or hitting permission issues.

## Approach

- **Location**: Use pytest’s **tmp_path** (and optionally **tmp_path_factory** for session scope). Do **not** use the user’s home directory.
  - Temp dir is writable and isolated; pytest manages retention and cleanup.
  - Avoids permission issues and keeps test artifacts out of home.
- **Lifecycle**: Create an empty SQLite DB in a fixture; yield path/URL to the test; dispose any engine. Pytest removes the temp dir after the run (with retention for recent runs on failure).
- **Isolation**: One DB per test (function-scoped fixture) by default so tests don’t affect each other. Use a session-scoped fixture only when tests are read-only or explicitly share state.

## References

- [pytest tmp_path](https://docs.pytest.org/en/stable/how-to/tmp_path.html) — temporary directories, cleanup, retention.
- Common pattern: session-scoped DB + function-scoped session for connection/session lifecycle; or function-scoped DB for full isolation.

---

## MariaDB and PostgreSQL: why it’s trickier

- A **running server** is required; there’s no “create a file and go” like SQLite.
- **Isolation** is harder: tests may share one server and use different databases or schemas; cleanup (drop DB/schema, or rollback) must be explicit.
- **Dialect and schema behavior** differ (e.g. PostgreSQL schemas, identifier quoting, DDL). Tests should run against real backends to catch dialect-specific bugs; SQLite alone is not enough per requirements (01-functional: SQLite, PostgreSQL, MariaDB).
- **Credentials and URLs** must be supplied (no default temp path); CI and local dev need a consistent way to get a URL without hardcoding secrets.

## PostgreSQL (implemented)

- **Fixture** `empty_postgres_db` (in `tests/integration/conftest.py`): yields `(url, target_schema)` for an empty PostgreSQL database. **Isolation**: a unique database is created per test and dropped on teardown (AUTOCOMMIT for CREATE/DROP DATABASE).
- **Sources** (in order):
  1. **Env URL**: If `MODELSYNC_TEST_POSTGRES_URL` is set, that host is used; the fixture connects to the `postgres` database to create/drop the per-test database. Use for CI, local installs, or cloud instances.
  2. **pytest-docker**: If the env var is not set, the fixture uses the `docker_services` and `docker_ip` fixtures from **pytest-docker**. A `postgres` service is defined in `tests/docker-compose.yml` (PostgreSQL 16). The compose file is selected via `tests/conftest.py` (`docker_compose_file`). To use **Podman** instead of Docker, set `MODELSYNC_TEST_POSTGRES_COMPOSE_CMD='podman compose'` (or `podman-compose`); `tests/conftest.py` overrides `docker_compose_command` from that env var.
- **Skip**: If neither the env URL nor Docker is available, tests that depend on `empty_postgres_db` are skipped (e.g. parametrized postgres runs are skipped).
- **Optional deps**: Install with `uv sync --all-extras` or `pip install -e ".[postgres]"` to get **psycopg** (driver) and **pytest-docker**. See [00-libraries-packages.md](00-libraries-packages.md).

## Test CLI (recommended workflow)

The **modelsync test** CLI provides a single entry point for the test workflow and clear exit codes when Postgres is unavailable:

- **`modelsync test check-container`** — Verifies the container runtime (Docker or Podman) and the Postgres image: runs a short-lived container (`pg_isready`), then removes it. Exit 0 on success; exit 1 with a clear message on failure (runtime not found, image pull failed, container start failed). Use **`MODELSYNC_CONTAINER_CMD`** (e.g. `docker` or `podman`) to choose the binary, or rely on auto-detection (docker then podman in PATH).
- **`modelsync test postgres up`** — Starts a long-lived Postgres container named `modelsync-postgres` on host port 5433 (image `postgres:16-alpine`). Prints `MODELSYNC_TEST_POSTGRES_URL=postgresql://postgres:postgres@127.0.0.1:5433/postgres` to set before running tests. Exit 1 if the container already exists or start fails.
- **`modelsync test postgres down`** — Stops and removes the long-lived container. Idempotent if the container does not exist.
- **`modelsync test run`** — Runs the test suite (pytest on `tests/`). **Exit codes:** 0 = all tests passed; 1 = test failure (or pytest invocation failed); **2** = tests were skipped because Postgres was not available (message instructs the user to run `check-container`, `postgres up`, set the URL, then `test run` again). Optional fail-fast: if `MODELSYNC_TEST_POSTGRES_URL` is unset and the perpetual container is not running, exit 2 immediately so the user knows before waiting for pytest.

## Options (MariaDB and other)

### Docker (or Podman) containers

- **Idea**: Start a MariaDB and a PostgreSQL container before tests (e.g. via pytest fixture, script, or CI job); connect with a known URL; tear down after the run.
- **Pros**: Reproducible, local and CI, no cloud dependency, matches “Linux + optional Docker/Podman” from the core rules. Can use official images and fixed versions.
- **Cons**: Requires Docker/Podman on the host; slower than SQLite; need to choose lifecycle (session vs. per-test container) and who starts/stops (pytest plugin, Makefile, CI step).
- **Suggestion**: Prefer a single container per backend per test run (session scope) to limit startup cost; use a dedicated database (or schema) per test or per run for isolation, with cleanup in fixtures.

### Cloud or hosted databases

- **Idea**: Use a hosted MariaDB/PostgreSQL instance (e.g. provider-managed DB or ephemeral “test” instances) and pass the URL via env or config.
- **Pros**: No container orchestration; can match production-like versions and features.
- **Cons**: Network and credentials; cost; vendor lock-in if tests assume one provider; secrets must not appear in logs (02-non-functional). The project is **cloud-agnostic**—tests should not *require* a specific cloud.
- **Suggestion**: If used, keep it optional (e.g. run PostgreSQL/MariaDB tests only when `MODELSYNC_TEST_POSTGRES_URL` or similar is set). Document that Docker/local is the primary recommended way to run multi-backend tests.

### Other

- **Local installs**: MariaDB/PostgreSQL installed on the host. Simple for daily dev but harder in CI and for version consistency; still need a standard way to pass URLs and to create/drop databases or schemas for isolation.
- **Test matrix**: In CI, consider a matrix: SQLite always; PostgreSQL and MariaDB when a container (or optional URL) is available, so PRs can run SQLite-only and full backends in a separate job or when configured.

## Summary

- **SQLite**: Current approach (tmp_path, `empty_sqlite_db` fixture, one DB file per test).
- **PostgreSQL**: Implemented via `empty_postgres_db` (env `MODELSYNC_TEST_POSTGRES_URL` or pytest-docker); per-test database for isolation.
- **MariaDB**: Not yet implemented; same pattern (env URL or Docker, per-test DB/schema) can be used when added.
