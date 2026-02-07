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

## Options (suggestions only; not implemented yet)

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

- SQLite: keep current approach (tmp_path, empty DB per test).
- MariaDB/PostgreSQL: document that Docker (or Podman) is the preferred way to get a real server for tests; optional env-based URLs for cloud or local installs; design fixtures for “create DB/schema, run test, tear down” without committing to a specific implementation yet.
