# dbconform

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
| Alter existing columns | ❌ | ✅ | ✅ | ✅ |
| Can fix schema drift | ❌ | ❌ | ✅ | ✅ |
| Works without migration history | ✅ | ❌ | ❌ | ✅ |
| Pure Python, `pip install` | ✅ | ✅ | ❌ | ✅ |
| SQLite constraint rebuild | ❌ | ❌ | ❌ | ✅ |
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
result = conform.apply_changes([Product, Cart])  # ConformPlan | ConformError

if isinstance(result, ConformError):
    print("Apply failed:", result.messages)
else:
    print(f"Applied {len(result.steps)} change(s). Schema is conformant.")
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

**NOT NULL on a column with existing NULLs:** If the model defines a column default, dbconform backfills NULLs automatically before adding the `NOT NULL` constraint. If there is no default, it returns a `ConformError` — backfill the column manually first, then retry.

**SQLite constraint limits:** SQLite cannot add CHECK, UNIQUE, or FOREIGN KEY constraints via `ALTER TABLE`. By default (`allow_sqlite_table_rebuild=True`), dbconform rebuilds the table (create new → copy data → drop old → rename), preserving all data and indexes. Set `allow_sqlite_table_rebuild=False` to skip rebuilds; skipped steps appear in `plan.skipped_steps`.

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
| `report_extra_tables` | `True` | Populate `plan.extra_tables` with tables in DB but not in your models |

`apply_changes()` additional flags:

| Flag | Default | What it controls |
|---|:---:|---|
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

## Errors

`ConformError` is **returned as a value**, not raised. Check for it with `isinstance`:

```python
if isinstance(result, ConformError):
    print(result.messages)        # list[str] — what went wrong
    print(result.target_objects)  # list of (object_type, name) e.g. [("table", "public.foo")]
```

`ConformError` also inherits from `Exception`, so `raise X from result` and `except ConformError` work if you prefer the exception pattern.

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
