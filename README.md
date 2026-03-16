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
| Correct schema drift (stateless) | ❌ | ❌ | ⚠️ | ✅ |
| Works without migration history | ✅ | ❌ | ❌ | ✅ |
| Pure Python, `pip install` | ✅ | ✅ | ❌ | ✅ |
| SQLite constraint rebuild | ❌ | ❌ | ❌ | ✅ |
| Safe defaults (no accidental drops) | ✅ | ⚠️ | ⚠️ | ✅ |
| In-process, programmatic | ✅ | ✅ | ❌ | ✅ |

> **Atlas** is a powerful schema platform — excellent for CI/CD pipelines and cloud drift monitoring. It's a Go CLI tool with its own infrastructure. `dbconform` is a Python library you call from application code.

---

## When to use dbconform

- You inherited a database and models, but the migrations have gone sideways.
- You're running SQLite in development and Postgres in production — and they've structurally diverged
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

### 1. Define your models (SQLAlchemy or SQLModel)

```python
from sqlalchemy import Column, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase

class Product(DeclarativeBase):
    __tablename__ = "product"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    price = Column(Float, nullable=False)

class Cart(DeclarativeBase):
    __tablename__ = "cart"
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
```

### 2. Compare (dry run)

```python
from dbconform import DbConform, ConformError

conform = DbConform(credentials={"url": "sqlite:///./mydb.sqlite"})
result = conform.compare([Product, Cart])

if isinstance(result, ConformError):
    print("Compare failed:", result.messages)
elif not result.steps:
    print("Database is up to date.")
else:
    for step in result.steps:
        print(step)
    print(result.sql())  # Full DDL script
```

### 3. Apply changes

```python
result = conform.apply_changes([Product, Cart])

if isinstance(result, ConformError):
    print("Apply failed:", result.messages)
else:
    print(f"Applied {len(result.steps)} change(s). Schema is conformant.")
```

### Using your own connection

```python
from sqlalchemy import create_engine

engine = create_engine("sqlite:///./mydb.sqlite")
with engine.connect() as conn:
    conform = DbConform(connection=conn)
    result = conform.compare([Product, Cart])
engine.dispose()
```

### PostgreSQL

```python
conform = DbConform(
    credentials={"url": "postgresql+psycopg://user:pass@host/db"},
    target_schema="public"
)
result = conform.apply_changes([Product, Cart])
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

## Safe by Default

`dbconform` will not drop tables or columns unless you explicitly opt in. The defaults are designed to be safe in production.

| Flag | Default | What it controls |
|---|:---:|---|
| `allow_drop_extra_tables` | `False` | DROP TABLE for tables not in your models |
| `allow_drop_extra_columns` | `False` | DROP COLUMN for columns not in your models |
| `allow_drop_extra_constraints` | `True` | DROP CONSTRAINT / DROP INDEX for removed constraints |
| `allow_shrink_column` | `False` | ALTER COLUMN that reduces size (may truncate data) |
| `allow_sqlite_table_rebuild` | `True` | SQLite table rebuild for CHECK/UNIQUE/FK changes |
| `report_extra_tables` | `True` | Populate `plan.extra_tables` with unrecognized tables |

`apply_changes()` additional flags:

| Flag | Default | What it controls |
|---|:---:|---|
| `commit_per_step` | `False` | Commit after each step (partial progress on failure) |
| `emit_log` | `True` | JSON-line logs for applied steps to stdout |
| `log_file` | `None` | Path to append logs to a file |

All flags are passed as keyword arguments:

```python
result = conform.apply_changes(
    [Product, Cart],
    allow_drop_extra_columns=True,
    allow_shrink_column=True
)
```

---

## SQLite and PostgreSQL

SQLite imposes strict limits on `ALTER TABLE`. Adding constraints (CHECK, UNIQUE, foreign keys) to an existing table requires rebuilding it entirely. `dbconform` handles this automatically — including data preservation, index recreation, and foreign key integrity — so you don't have to think about it.

PostgreSQL uses a different DDL dialect. `dbconform` abstracts both behind the same API.

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
