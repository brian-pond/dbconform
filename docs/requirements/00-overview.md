# Overview

**modelsync** — Production-ready, multi-database schema drift correction (Python).

## Project summary
The Python ecosystem lacks a mature, multi-database, production-ready solution for automated drift correction beyond what Alembic provides. modelsync aims to be that solution.

**Core function:** Compare code models (SQLAlchemy/SQLModel) to a live SQL database and, when drift exists, produce and optionally apply DDL and data operations so the database matches the models (schema parity).

## Technology Stack
- Primarily a **Python library** with API entry points for other programs to use; callers import modelsync and pass their models and connection (or credentials) to functions such as `compare()` or `do_sync()`.
- A **CLI** exists primarily for **running tests** in Phase 1; a minimal sync CLI may be added later for ad-hoc or CI use.
- Minimum Python 3.11, developed with Python 3.14.

## Goals
- **Single source of truth**: Code models (SQLAlchemy/SQLModel) define the desired schema; the database is brought into parity with them.
- **Safe by default**: Operations run in dry-run first; the user confirms before any DDL or data operations are applied.
- **CI/CD and scriptable**: Sync is driven via the library API so scripts and pipelines can run compare/sync with explicit confirmation or apply flags.
- **Auditability**: All changes are logged so they can be reviewed and audited.

## In-scope
- **Model frameworks:** SQLAlchemy, SQLModel.
- **Databases:** SQLite, PostgreSQL, MariaDB.

## Inspiration
* https://github.com/hunyadi/pysqlsync
* https://github.com/djrobstep/migra
* https://github.com/djrobstep/results

## Out-of-scope
- **Other databases**: SQL Server, Oracle, and other database engines beyond SQLite, PostgreSQL, and MariaDB.
- **Migrations and versioning**: modelsync does not implement migration history, versioned migrations, or upgrade/downgrade chains; that remains the domain of tools such as Alembic.
