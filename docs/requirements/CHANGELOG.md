# Requirements changelog

All notable changes to the requirements docs are recorded here.

## [Unreleased]

### Added

- Initial requirements scaffold (00-overview, 01-functional, 02-non-functional).
- **00-overview**: Goals (single source of truth, safe by default, CI/CD and scriptable, auditability); in-scope models (SQLAlchemy, SQLModel) and DBs (SQLite, PostgreSQL, MariaDB); out-of-scope (other DBs, migration/versioning); technology stack (library-first, CLI for tests in Phase 1).
- **01-functional**: Feature list; sync flow and confirmation (CLI prompt, API apply default no, output-only); default add/alter only (no drops unless opted in); schema parity scope (tables, columns, keys, constraints, indexes, comments; future: sequences, triggers, enums); data operations (backfill, type change, data-loss warning); column rename as Phase 2; model discovery and API (no auto-discovery, pass one or many models to e.g. `compare()` / `do_sync()`); database connection (caller passes connection or credentials); CLI scope (Phase 1: primarily for running tests); acceptance criteria as unit-test scenarios.
- **02-non-functional**: Security (no secrets in logs); deployment (Linux Phase 1, PyPI/pip); observability (structured, machine-parseable logs to stdout; optional log file).

### Changed
- **Review (all docs):** Clarified and tightened wording; removed duplication; fixed typo ("is become" → "is to become"); overview tagline and single-sentence core function; in-scope as bullet list; feature list condensed; sync flow ordered API-first with CLI conditional; acceptance criteria merged into one required-coverage list; NFRs: Performance placeholder and non-functional acceptance criteria added.

### Added
- **01-functional:** Transaction behavior (configurable; default all-or-nothing, rollback on failure). Plan and DDL order (valid execution order, dependencies respected). Connection lifecycle when credentials passed (modelsync opens, runs sync, closes). Target schema mandatory for schema-supporting DBs (e.g. PostgreSQL). Error handling: structured Error object identifying which objects failed and why. NOT NULL on column with NULLs: apply default if present, else error and require caller to backfill. Identifiers and quoting: follow target database rules (e.g. PostgreSQL double quotes, MariaDB backticks).
- **02-non-functional:** Dependencies: Phase 1 support latest LTS versions of SQLAlchemy and SQLModel.
- **docs/technical/00-libraries-packages.md:** Version policy (Phase 1) referencing 02-non-functional.
- **01-functional:** Target schema: for DBs without schemas (e.g. SQLite), target-schema argument may be omitted or ignored.
- **02-non-functional:** Documentation: public API must be documented (e.g. README and API reference).
