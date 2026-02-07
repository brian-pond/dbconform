# Libraries and packages

Single place for modelsync library and package choices: rationale, alternatives, and links to requirement docs. See [.cursor/rules/requirements.mdc](../../.cursor/rules/requirements.mdc) for the requirements index.

## Purpose

- Document **chosen** packages and **rationale** per category.
- Record **alternatives** and **optional / later** dependencies.
- Link to requirement docs where relevant.

## Principles

- **Minimal deps** — add optional or heavy stacks only when justified.
- **Cloud agnostic** — no provider-specific SDKs; deployment and secrets are vendor-neutral.

## Runtime dependencies

- **SQLAlchemy** (>=2.0): Used for metadata inspection (model schema extraction) and reflection (database schema). SQLModel builds on SQLAlchemy; callers may pass either SA or SQLModel models. See [01-functional](../requirements/01-functional.md) (Model frameworks).

## Version policy (Phase 1)

- SQLAlchemy and SQLModel: support **latest LTS versions** per [02-non-functional](../requirements/02-non-functional.md). Pin or bound versions in pyproject.toml accordingly.
