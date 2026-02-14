# Overview

**modelsync** — Production-ready, multi-database schema drift correction (Python).

## Project summary
The Python ecosystem lacks a mature, multi-database, production-ready solution for automated drift correction beyond what Alembic provides. modelsync aims to be that solution.

**Core function:** Compare code models (SQLAlchemy/SQLModel) to a live SQL database and, when drift exists, produce and optionally apply DDL and data operations so the database matches the models (schema parity). modelsync has four core functions: internal schema, adapters (ingest), compare, and DDL generation; see [docs/technical/02-architecture.md](../technical/02-architecture.md) for details.

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
- **Model frameworks:** SQLAlchemy, SQLModel, Django Models, Tortoise ORM, Piccolo ORM.
- **Databases:** SQLite, PostgreSQL, MariaDB.

## Inspiration

- **pysqlsync** (https://github.com/hunyadi/pysqlsync): Primary reference for model-to-database sync. We adopted its split of an internal schema from two sides (formation from code, discovery from DB), the Mutator-style diff-to-DDL flow, dialect-specific DDL modules, and options for drops (allow_drop, report extra tables). modelsync uses SQLAlchemy/SQLModel and synchronous execution rather than dataclasses and async.
- **migra** and **results** (https://github.com/djrobstep/migra, https://github.com/djrobstep/results): DB-to-DB comparison tools. Components that informed modelsync's design (we do not ship or depend on them):
  - **`differences()`** (results/dbdiff/util.py): Compare two keyed structures and return added, removed, modified, and unmodified. We use the same pattern in `schema/diff.py` to compare model-side internal schema vs database-side internal schema.
  - **Dependency-ordered DDL**: Migra's `changes.py` and `statements_from_differences()` apply creations/drops in dependency order (e.g. create tables before FKs). Our `SyncPlanBuilder` and `_topological_table_order()` follow the same idea for table creation.
  - **Table/column change structure**: Migra's `get_table_changes()` diffs columns (added/removed/modified) and emits ALTERs. Our `TableDiff` and plan builder use the same kind of per-table diff (added_columns, modified_columns, etc.) to generate ALTER steps.

## Out-of-scope
- **Other databases**: SQL Server, Oracle, and other database engines beyond SQLite, PostgreSQL, and MariaDB.
- **Migrations and versioning**: modelsync does not implement migration history, versioned migrations, or upgrade/downgrade chains; that remains the domain of tools such as Alembic.
