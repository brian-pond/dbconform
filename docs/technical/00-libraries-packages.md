# Libraries and packages

Single place for modelsync library and package choices: rationale, alternatives, and links to requirement docs. See [.cursor/rules/requirements.mdc](../../.cursor/rules/requirements.mdc) for the requirements index.

## Purpose

- Document **chosen** packages and **rationale** per category.
- Document **alternatives** and **optional / later** dependencies.
- Link to requirement docs where relevant.

## Principles

- **Minimal deps** — add optional or heavy stacks only when justified.
- **Cloud agnostic** — no provider-specific SDKs; deployment and secrets are vendor-neutral.

## Runtime dependencies

- **SQLAlchemy** (>=2.0): Used for metadata inspection (model schema extraction) and reflection (database schema). SQLModel builds on SQLAlchemy; callers may pass either SA or SQLModel models. See [01-functional](../requirements/01-functional.md) (Model frameworks).

## Optional dependencies (test / backend)

- **`[postgres]`** (pyproject.toml): Used only for running integration tests against PostgreSQL.
  - **psycopg** ([binary] extra, >=3): PostgreSQL driver for SQLAlchemy (`postgresql+psycopg://`). Chosen over psycopg2 for modern API and maintenance. See [01-test-database.md](01-test-database.md).

- **`[dev]`** (pyproject.toml): Development and test tooling. **typer** (>=0.9): CLI framework for the `modelsync` script (e.g. `modelsync test run`, `modelsync test postgres up`). See [01-functional](../requirements/01-functional.md) (CLI scope) and [01-test-database.md](01-test-database.md).

## Version policy (Phase 1)

- SQLAlchemy and SQLModel: support **latest LTS versions** per [02-non-functional](../requirements/02-non-functional.md). Pin or bound versions in pyproject.toml accordingly.
- Package version: **pyproject.toml** is the single source of truth. Bump `version` there when releasing. `__version__` in `src/modelsync/__init__.py` is derived at runtime via `importlib.metadata.version("modelsync")` (fallback `"0.0.0"` if not installed).

## Distribution

- **Build:** From project root run `uv build`. Requires the `build` package (in `[project.optional-dependencies]` dev). Produces a wheel and sdist in `dist/` (e.g. `dist/modelsync-0.1.0-py3-none-any.whl`). The wheel is the primary artifact for installing into other applications.
- **Consumption:** Other projects can install via editable path (`pip install -e /path/to/modelsync`), from a built wheel (`pip install path/to/modelsync-*.whl`), or from a private index. No open-source license is set; project is private.
