# Architecture (high level)

High-level data flow for comparing code models to a live database and producing a sync plan. See [docs/requirements/01-functional.md](../requirements/01-functional.md) for required behavior.

## Core functions

modelsync is organized around four distinct functions:

1. **Internal schema** — Defines a neutral, library-agnostic representation of a SQL table's schema (tables, columns, constraints, indexes). No dependency on SQLAlchemy, Django, or other ORMs.
2. **Adapters (ingest)** — Take well-known third-party models (SQLAlchemy, SQLModel; later Django, Tortoise, Piccolo) and produce the modelsync internal schema. Ingestion is **read-only**: we do not modify the caller's model classes or their `__table__` / columns.
3. **Compare** — Reflect a live database into the internal schema and compare it to the model-derived internal schema; produce a structured diff (added, removed, modified).
4. **DDL generation** — From the comparison result, build an ordered plan and generate dialect-specific DDL to bring the target database into parity with the model.

The following diagram and sections describe how these functions are wired together.

**Package layout:** The codebase is organized as subpackages under `modelsync`: `internal` (neutral schema types and type names), `adapters` (third-party model → internal), `compare` (DB reflection and diff), `plan` (diff → ordered steps), and `sql_dialect` (steps → DDL). The `schema` package is retained as a backward-compatibility re-export of the public API from internal, adapters, and compare.

## Internal schema: design goals

The **internal schema** is modelsync’s intermediate representation of SQL schema. Its overarching goal:

- **Lightweight, frozen/immutable** — Table, Column, Index, Constraint (and related types) are minimal, immutable structures, so they are easy to compare, hash, and pass around without side effects. The current implementation uses frozen dataclasses (e.g. `@dataclass(frozen=True)`); the design requirement is immutability and minimal surface, not a specific Python mechanism.
- **Lingua franca** — A single representation that sits between **ORMs** (SQLAlchemy, SQLModel, Django, Tortoise, Piccolo) and **databases** (SQLite, PostgreSQL, MariaDB). Each side adapts to or from this representation; the core compare/diff and migration-generation logic speaks only the internal schema.
- **Analogous roles in other ecosystems:**
  - **AST** in compilers: universal intermediate representation between frontends (languages) and backends (targets).
  - **OpenAPI** for REST APIs: language- and implementation-agnostic contract for APIs.
  - **Protocol Buffers** as an IDL: neutral, well-defined schema for serialization and RPC.
- **Minimal, ORM-agnostic, DB-agnostic** — Only what is needed for **comparison and migration generation**. No ORM or database specifics; those are handled by adapters (model → internal) and dialects (internal → DDL / reflection → internal).

Keeping the internal schema minimal and immutable ensures it remains a stable, auditable basis for diff and plan building.

```mermaid
flowchart LR
  subgraph inputs [Inputs]
    Models[Code models\nSQLAlchemy / SQLModel /\nDjango / Tortoise / Piccolo]
    DB[(Live DB)]
  end
  subgraph internal [Internal schema]
    MS[ModelSchema]
    DS[DatabaseSchema]
  end
  subgraph core [Core]
    Diff[SchemaDiffer]
    Plan[SyncPlanBuilder]
  end
  subgraph output [Output]
    PlanOut[SyncPlan]
  end
  Models --> MS
  DB --> DS
  MS --> Diff
  DS --> Diff
  Diff --> Plan
  MS --> Plan
  DS --> Plan
  Plan --> PlanOut
```

- **ModelSchema** / **DatabaseSchema**: Internal schema (lightweight, frozen/immutable) representation of tables, columns, constraints, and indexes so the two sides can be compared by name/identity. See "Internal schema: design goals" above.
- **SchemaDiffer**: Compares model schema to DB schema; produces added, removed, modified, and extra (unmanaged) tables.
- **SyncPlanBuilder**: Builds an ordered list of DDL and data-operation steps from the diff, with dependency-safe ordering and configurable drop behavior.
- **ModelSync** (facade): Library entry point; accepts connection or credentials and target schema, exposes `compare()` returning a **SyncPlan**.

## Types

Column types are represented in the internal schema as **data_type_name** (a string on `ColumnDef`). The flow is:

1. **Model → internal**: SQLAlchemy column types are compiled with the connection dialect (`column.type.compile(dialect)`), producing a type string. Optionally, a schema normalizer (modelsync Dialect) rewrites the table so type strings match a neutral form (e.g. PostgreSQL: `CHARACTER VARYING(255)` → `VARCHAR(255)`, `DOUBLE PRECISION` → `FLOAT`).
2. **Reflection → internal**: Reflected tables are built from DB metadata (same compile); then the backend’s Dialect **normalize_reflected_table** and **to_neutral_type** rewrite columns so they use the same neutral type strings (e.g. SERIAL/nextval → `default=None`, `autoincrement=True`, neutral type string).
3. **Neutral → DDL**: When generating SQL, each Dialect maps **data_type_name** to platform-specific DDL (e.g. SQLite uses data_type_name as-is; PostgreSQL maps INTEGER + autoincrement PK → SERIAL). Shared parsing (e.g. VARCHAR length) lives on the base Dialect (`_parse_varchar_length`).

A single neutral type set and per-dialect “to neutral” / “to DDL” mapping keeps comparison and DDL generation consistent and makes adding a new backend (e.g. MariaDB) a matter of implementing one Dialect.
