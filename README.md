# dbconform

> **New in this release:** Auto-generate dbt `schema.yml` files from your SQLAlchemy models — perfect for protecting your data mart tables. [Jump to dbt integration →](#dbt-integration-optional)

**Your database schema has drifted. `dbconform` fixes it.**

Over time, databases can diverge from your SQLAlchemy models — columns get added manually, constraints go missing, a hotfix gets applied directly to the DB and never captured in code. This is *database drift*, and it's a real-world, compounding problem.

SQLAlchemy's `create_all()` only creates new tables. Alembic works well for disciplined linear migrations, but it has no answer for drift: when your database diverges from your migration history, you're on your own.

`dbconform` inspects your live database, compares it against your SQLAlchemy (or SQLModel) models, and either tells you exactly what's wrong — or *fixes* it.

```python
from dbconform import DbConform
from my_app.my_alchemy_schemas import Product, Cart # your own models

conform = DbConform(credentials={"url": "sqlite:///./mydb.sqlite"})
result = conform.apply_changes([Product, Cart])

print(f"Applied {len(result.steps)} change(s). Target database schema is conformant.")
```

That's it. No migration files, history table, CLI, or additional infrastructure.

✅ &nbsp;&nbsp;Supports both sync/async Python\
✅ &nbsp;&nbsp;SQLite\
✅ &nbsp;&nbsp;PostgreSQL\
🏗️ &nbsp;&nbsp;MariaDB (in-scope for future development)

---

## Why not Alembic?

Alembic is excellent when you start clean -and- stay disciplined. But that's just not always the situation we find ourselves in.  So I wanted a tool that just fixes the problems, and lets me get on with my work:

| Capability | SQLAlchemy `create_all` | Alembic | Atlas | **dbconform** |
|---|:---:|:---:|:---:|:---:|
| Create new tables | ✅ | ✅ | ✅ | ✅ |
| Alter existing tables | ❌ | ✅ | ✅ | ✅ |
| Can fix schema drift | ❌ | ❌ | ✅ | ✅ |
| Works without migration history | ✅ | ❌ | ❌ | ✅ |
| Pure Python, `pip install` | ✅ | ✅ | ❌ | ✅ |
| SQLite rebuild capabilities | ❌ | ❌ | ❌ | ✅ |
| Safe defaults (no accidental drops) | ✅ | ⚠️ | ⚠️ | ✅ |
| In-process, programmatic | ✅ | ✅ | ❌ | ✅ |

> **Atlas** is a powerful schema platform — excellent for CI/CD pipelines and cloud drift monitoring. It's a Go CLI tool with its own infrastructure. `dbconform` is a Python library you call from application code.

---

## When to use dbconform

- You inherited a database and models, but the migrations have gone sideways.
- Your databases in development and production have structurally diverged.
- You want to programmatically enforce schema conformance at application startup (*one of my personal favorites*)
- You don't want to manage migration history at all, with something like Alembic.
- Someone ran a hotfix directly on the database and now you need to reconcile.

---

## Installation

```bash
pip install dbconform
```

Optional extras:

```bash
pip install dbconform[postgres]        # PostgreSQL support (psycopg)
pip install dbconform[async]           # Async drivers (aiosqlite, asyncpg)
pip install dbconform[async,postgres]  # Both
pip install dbconform[dbt]             # dbt schema.yml generation (pyyaml)
```

**Requirements:** Python 3.11+

---

## Quick Start

### Define your models (SQLAlchemy or SQLModel)

```python
from sqlalchemy import Column, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

class Product(Base):
    __tablename__ = "product"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    price = Column(Float, nullable=False)

class Cart(Base):
    __tablename__ = "cart"
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
```

### Compare (dry run)

`compare()` builds a **`ConformPlan`** and does not change the database.

```python
from dbconform import DbConform, ConformError

conform = DbConform(credentials={"url": "sqlite:///./mydb.sqlite"})
result = conform.compare([Product, Cart])  # ConformPlan | ConformError

if isinstance(result, ConformError):
    print("Compare failed:", result.messages)
elif not result.steps:
    print("Database is up to date.")
else:
    result.print_summary()
```

**Ways to inspect the plan:**

- **`print_summary()`** / **`summary()`** — Human-readable counts and descriptions: planned steps, **extra tables** (present in the DB but not in your models), and **skipped steps** (drift left behind because of safety flags or backend limits).
- **`sql()`** — One multi-line string of DDL (plus comments where the plan includes SQLite table rebuilds). **`statements()`** — List of non-empty SQL strings from individual steps (handy for drivers that execute one statement at a time).
- **`steps`**, **`extra_tables`**, **`skipped_steps`** — Use these attributes directly if you need structured data for your own reporting or tooling.

### Apply changes

```python
# apply_changes() raises ConformError by default on failure
try:
    result = conform.apply_changes([Product, Cart])  # ConformPlan on success
    print(f"Applied {len(result.steps)} change(s).")
    if result.skipped_steps:
        print(f"Warning: {len(result.skipped_steps)} skipped step(s) — see stderr from apply.")
except ConformError as e:
    print("Conform failed:", e.messages)  # includes blocking skipped steps
    if e.plan:
        e.plan.print_summary()  # inspect partial plan and skipped steps
```

By default all steps run in a **single transaction** — any failure rolls back everything. Set `commit_per_step=True` to commit after each step so prior steps persist if a later one fails.

Each applied step is also emitted as a **JSON-line log** to stdout. Pass `emit_log=False` to suppress it, or `log_file="path/to/conform.log"` to append to a file (no credentials are ever included in logs).

---

## Connections

### Connection options

Pass `credentials` and dbconform manages the connection lifecycle, or pass your own `connection` and manage it yourself.

```python
# SQLite — credentials
conform = DbConform(credentials={"url": "sqlite:///./mydb.sqlite"})

# PostgreSQL — credentials (target_schema is required)
conform = DbConform(
    credentials={"url": "postgresql+psycopg://user:pass@host/db"},
    target_schema="public"
)

# Or bring your own connection (any supported backend)
from sqlalchemy import create_engine

engine = create_engine("sqlite:///./mydb.sqlite")
with engine.connect() as conn:
    conform = DbConform(connection=conn)
    result = conform.compare([Product, Cart])
engine.dispose()
```

### Async

```python
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from dbconform import AsyncDbConform, ConformError

async def main():
    engine = create_async_engine("sqlite+aiosqlite:///./mydb.sqlite")
    async with engine.connect() as conn:
        conform = AsyncDbConform(async_connection=conn)
        result = await conform.apply_changes([Product, Cart])
    await engine.dispose()

asyncio.run(main())
```

---

## What dbconform conforms

By default (add/alter only — no drops unless opted in):

| Element | What dbconform does |
|---|---|
| **Tables** | Create missing tables |
| **Columns** | Add missing; alter type, nullability, and default |
| **Primary keys** | Add missing |
| **Unique constraints** | Add/remove |
| **Foreign keys** | Add/remove |
| **Check constraints** | Add/remove |
| **Indexes** | Create/drop |
| **Comments** | Sync table and column comments (where the backend supports them) |

Steps are emitted in **dependency order** — e.g., a table is created before any foreign key that references it.

**Column defaults:** Python scalar defaults on SQLAlchemy/SQLModel columns (e.g. `default=date(1970, 1, 1)` on a `DATE` column) are emitted as properly quoted literals so the database interprets them correctly.

**ADD NOT NULL column on a non-empty table:** By default the step is **skipped** (see `plan.skipped_steps`) so a single invalid `ADD COLUMN … NOT NULL` is never emitted. Opt in with `allow_not_null_backfill=True` to run a multi-step plan: add nullable → `UPDATE` backfill → `SET NOT NULL`. Backfill sources (stateless, no built-in column mappings): `Column.info["dbconform_backfill_sql"]`, `Column.info["dbconform_backfill"]` (peer column on the same table), column `server_default` / default, or — when `backfill_sentinel_timestamps=True` — `1900-01-01` for date/timestamp types.

**SQLite constraint limits:** SQLite cannot add CHECK, UNIQUE, or FOREIGN KEY constraints via `ALTER TABLE`. By default (`allow_sqlite_table_rebuild=True`), dbconform rebuilds the table (create new → copy data → drop old → rename), preserving all data and indexes. Set `allow_sqlite_table_rebuild=False` to skip rebuilds; skipped steps appear in `plan.skipped_steps`.

**Skipped steps and drift severity:** Every skipped step and every extra table emits a **warning on stderr** so operators see remaining drift. Each `SkippedStep` has `category` and `severity` (`warning` or `error`). When any error-severity skip remains (harmful asymmetry): `compare()` **returns** `ConformError`; `apply_changes()` **raises** `ConformError` (or returns it with `raise_on_error=False`). No DDL is applied when error-severity skips exist.

| Situation | Severity |
|-----------|----------|
| Extra DB column, nullable or with DEFAULT | `warning` |
| Extra DB column, NOT NULL without DEFAULT | `error` |
| Model column/constraint missing in DB (blocked add, NOT NULL backfill, SQLite rebuild off, …) | `error` |
| Extra DB constraint/index not dropped (`allow_drop_extra_constraints=False`) | `warning` |
| Column shrink blocked | `warning` |
| Extra tables (in DB, not in models) | warning on stderr only |

Inspect `result.plan.skipped_steps`, `result.plan.blocking_skipped_steps()`, or `result.plan.has_blocking_skipped_steps()` when `isinstance(result, ConformError)` and `result.plan` is set; otherwise use the returned `ConformPlan` directly.

**Future (not yet in scope):** sequences, triggers, enums.

---

## Safe by Default

`dbconform` will not drop tables or columns unless you explicitly opt in. The defaults are designed to be safe in production.

| Flag | Default | What it controls |
|---|:---:|---|
| `allow_drop_extra_tables` | `False` | DROP TABLE for tables not in your models |
| `allow_drop_extra_columns` | `False` | DROP COLUMN for columns not in your models |
| `allow_drop_extra_constraints` | `True` | DROP CONSTRAINT / DROP INDEX for removed constraints |
| `allow_shrink_column` | `False` | ALTER COLUMN that reduces size (may truncate data) |
| `allow_sqlite_table_rebuild` | `True` | SQLite table rebuild for CHECK/UNIQUE/FK changes |
| `allow_not_null_backfill` | `False` | Multi-step ADD NOT NULL on tables that already have rows |
| `backfill_sentinel_timestamps` | `False` | Use `1900-01-01` sentinel when no other backfill source applies |
| `report_extra_tables` | `True` | Populate `plan.extra_tables` with tables in DB but not in your models |

`apply_changes()` additional flags:

| Flag | Default | What it controls |
|---|:---:|---|
| `raise_on_error` | `True` | Raise `ConformError` on failure; set `False` to return it for programmatic inspection |
| `commit_per_step` | `False` | Commit after each step (partial progress persists on failure) |
| `emit_log` | `True` | JSON-line log to stdout for each applied step |
| `log_file` | `None` | Path to also append logs to a file |

All flags are passed as keyword arguments:

```python
result = conform.apply_changes(
    [Product, Cart],
    allow_drop_extra_columns=True,
    allow_shrink_column=True
)
```

---

## Error Handling

### `apply_changes()` — Raises by default

`apply_changes()` **raises** `ConformError` when conformity fails (error-severity skipped steps or apply failures). This reflects execution semantics: when you command "make it conform," failure should interrupt flow.

```python
from dbconform import ConformError

try:
    plan = conform.apply_changes([Product, Cart])
    print(f"Success: {len(plan.steps)} step(s) applied")
except ConformError as e:
    print("Conformity failed:", e.messages)
    print("Affected objects:", e.target_objects)
    if e.plan:
        e.plan.print_summary()  # inspect partial plan and blocking skipped steps
```

**Advanced: return instead of raise**

For programmatic inspection (e.g. CI pipelines analyzing drift), set `raise_on_error=False`:

```python
result = conform.apply_changes([Product, Cart], raise_on_error=False)
if isinstance(result, ConformError):
    # Analyze blocking issues without exception handling
    for step in result.plan.skipped_steps:
        log_skipped_step(step.category, step.severity, step.reason)
```

### `compare()` — Always returns

`compare()` is an **analysis operation**. Drift detection is the purpose, so it always **returns** `ConformPlan | ConformError` without raising:

```python
result = conform.compare([Product, Cart])
if isinstance(result, ConformError):
    print("Blocking issues found:", result.messages)
    result.plan.print_summary()
else:
    print(f"Would apply {len(result.steps)} step(s)")
```

---

## dbt Integration (optional)

If you use **dbt** alongside SQLAlchemy, you likely know the pain: your mart tables need a `schema.yml` to get `not_null`, `unique`, and `relationships` tests — and hand-writing that file is tedious and error-prone.

**Why marts specifically?** Staging and intermediate models are dbt's internal plumbing — transient, frequently restructured, and typically not worth the effort of defining SQLAlchemy models. But your **mart tables** are different. They're the final output: the tables Tableau, Power BI, Superset, or your data scientists query every day. If a column goes nullable, a foreign key vanishes, or a constraint is silently dropped, *your dashboards break*. That's exactly what dbconform was built to protect — and now it can tell dbt about those protections too.

The pattern: define your mart tables as SQLAlchemy models, run `dbconform` to keep the schema conformant at the database level, and use `dbconform[dbt]` to generate the `schema.yml` so dbt can test the same guarantees at runtime.

### Library

```python
from dbconform.integrations.dbt import generate_schema_yml
from pathlib import Path
from myapp.marts import CustomerMart, SalesFact, ProductDim

# Print to stdout
print(generate_schema_yml([CustomerMart, SalesFact, ProductDim]))

# Or write directly
generate_schema_yml(
    [CustomerMart, SalesFact, ProductDim],
    output_path=Path("models/marts/schema.yml"),
)
```

### CLI

```bash
# Unified schema.yml for all mart models
dbconform dbt generate \
    myapp.marts:CustomerMart \
    myapp.marts:SalesFact \
    myapp.marts:ProductDim \
    --output models/marts/schema.yml

# One file per model
dbconform dbt generate \
    myapp.marts:CustomerMart \
    myapp.marts:SalesFact \
    --output-dir models/marts/ --per-model
```

### What gets generated

Given a `CustomerMart` model with a primary key, a non-nullable FK to `dim_date`, and a column comment:

```yaml
version: 2
models:
  - name: customer_mart
    description: Final customer dimension for BI consumption
    columns:
      - name: customer_id
        data_tests:
          - not_null
          - unique
      - name: date_key
        data_tests:
          - not_null
          - relationships:
              to: ref('dim_date')
              field: date_key
      - name: lifetime_value
        data_tests:
          - not_null
```

> **dbt version note:** `data_tests:` is the current key name (dbt v1.8+). The older `tests:` key still works for backward compatibility but is considered legacy.

**Mapping summary:**

| SQLAlchemy model | dbt test |
|---|---|
| Primary key column | `not_null` + `unique` |
| `nullable=False` column | `not_null` |
| Single-column `UniqueConstraint` | `unique` |
| `ForeignKey(...)` | `relationships` (uses `ref('table_name')`) |
| `Column(..., comment="...")` | `description:` |
| `__table_args__ = {"comment": "..."}` | model `description:` |

> **FK references:** Foreign keys always emit `ref('table_name')`. If the referenced table is a dbt `source()` rather than a model, edit those entries manually — or use the library API to post-process the YAML string before writing.

> **Multi-column unique constraints** (e.g. `UniqueConstraint("col_a", "col_b")`) cannot be expressed with dbt's built-in tests. A `meta.dbconform_notes` comment is added to remind you to add `dbt_utils.unique_combination_of_columns` manually.

---

## Contributing

Issues and pull requests are welcome. For local development:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,async,postgres]"
```

Running tests (Docker or Podman required for PostgreSQL tests):

```bash
dbconform test run
```

To see the installed `dbconform` version:

```bash
dbconform version
```

See `tests/TESTS_README.md` for the full test organization.

---

## License

MIT
