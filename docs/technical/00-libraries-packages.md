# Libraries and packages

Single place for dbconform library and package choices: rationale, alternatives, and links to requirement docs. See [.cursor/rules/requirements.mdc](../../.cursor/rules/requirements.mdc) for the requirements index.

## Purpose

- Document **chosen** packages and **rationale** per category.
- Document **alternatives** and **optional / later** dependencies.
- Link to requirement docs where relevant.

## Principles

- **Minimal deps** — add optional or heavy stacks only when justified.
- **Cloud agnostic** — no provider-specific SDKs; deployment and secrets are vendor-neutral.

## Runtime dependencies

- **SQLAlchemy** (>=2.0): Used for metadata inspection (code models → model-side internal schema) and reflection (database-side internal schema). SQLModel builds on SQLAlchemy; callers may pass either SA or SQLModel models. See [01-functional](../requirements/01-functional.md) (Model frameworks).

## Optional dependencies (test / backend)

- **`[postgres]`** (pyproject.toml): Used only for running integration tests against PostgreSQL.
  - **psycopg** ([binary] extra, >=3): PostgreSQL driver for SQLAlchemy (`postgresql+psycopg://`). Chosen over psycopg2 for modern API and maintenance. See [01-test-database.md](01-test-database.md).

- **`[dev]`** (pyproject.toml): Development and test tooling. **typer** (>=0.9): CLI framework for the `dbconform` script (e.g. `dbconform test run`, `dbconform test postgres up`). **commitizen** (`cz`): semver bumps via the root `Makefile` `release` target (`uv run cz`). **build**: PEP 517 builds (`python -m build`). **twine**: upload wheels/sdists to an index. See [01-functional](../requirements/01-functional.md) (CLI scope) and [01-test-database.md](01-test-database.md).

## Version policy (Phase 1)

- SQLAlchemy and SQLModel: support **latest LTS versions** per [02-non-functional](../requirements/02-non-functional.md). Pin or bound versions in pyproject.toml accordingly.
- Package version: **pyproject.toml** is the single source of truth. Bump `version` there when releasing. `__version__` in `src/dbconform/__init__.py` is derived at runtime via `importlib.metadata.version("dbconform")` (fallback `"0.0.0"` if not installed).

## Distribution

- **Build:** From project root run `uv build`. Requires the `build` package (in `[project.optional-dependencies]` dev). Produces a wheel and sdist in `dist/` (e.g. `dist/dbconform-0.1.0-py3-none-any.whl`). The wheel is the primary artifact for installing into other applications.
- **Consumption:** Other projects can install via editable path (`pip install -e /path/to/dbconform`), from a built wheel (`pip install path/to/dbconform-*.whl`), or from a private index. No open-source license is set; project is private.
