# dbconform

A Python library to conform database schema to models: keep your database schema in line with your SQLAlchemy or SQLModel definitions.

## Prerequisites

- Python 3.11+

## Installing from PyPI

```bash
pip install dbconform
```

Optional extras:

- **`[postgres]`** — PostgreSQL driver (psycopg) for connecting to PostgreSQL
- **`[async]`** — Async drivers (aiosqlite, asyncpg) for `AsyncDbConform`

```bash
pip install dbconform[postgres]       # PostgreSQL support
pip install dbconform[async]          # Async (SQLite + PostgreSQL)
pip install dbconform[async,postgres] # Both
```

## Usage

Use dbconform as a library: define your models (SQLAlchemy or SQLModel), then compare them to the database. By default, only a plan is produced; apply only when you explicitly opt in.

### Quick start

**1. Create a `DbConform` instance** — pass either credentials (dbconform manages the connection) or your own connection:

- **`credentials={"url": "sqlite:///./mydb.sqlite"}`** — dbconform opens the database, runs your call, then closes it.
- **`connection=engine.connect()`** — you provide an open connection and close it when done.

For PostgreSQL, also pass **`target_schema="public"`** (or your schema name). For SQLite you can omit it.

**2. `compare(models)`** — dry run: returns a plan of steps (create table, add column, etc.) without executing anything. Use `result.sql()` to get the DDL script.

**3. `apply_changes(models)`** — same as compare, but runs the plan against the database. All-or-nothing by default; rollback on failure.

---

Define your models and pass them (one class or a list) to `compare()` or `apply_changes()`.

```python
from sqlalchemy import Column, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase

from dbconform import DbConform, ConformError

# Define your models (SQLAlchemy or SQLModel)
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

# Compare: get a plan without applying
conform = DbConform(credentials={"url": "sqlite:///./mydb.sqlite"})
result = conform.compare([Product, Cart])

if isinstance(result, ConformError):
    print("Compare failed:", result.messages)
else:
    if not result.steps:
        print("Database is up to date.")
    else:
        for step in result.steps:
            print(step)
        print(result.sql())  # Full DDL script
```

**Using your own connection** — you manage the connection lifecycle:

```python
from sqlalchemy import create_engine

engine = create_engine("sqlite:///./mydb.sqlite")
with engine.connect() as conn:
    conform = DbConform(connection=conn)
    result = conform.compare([Product, Cart])
engine.dispose()
```

**Async usage** — use `AsyncDbConform` with async driver URLs (`sqlite+aiosqlite://`, `postgresql+asyncpg://`). Install the `[async]` extra: `pip install dbconform[async]`.

```python
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from dbconform import AsyncDbConform, ConformError

async def main():
    engine = create_async_engine("sqlite+aiosqlite:///./mydb.sqlite")
    async with engine.connect() as conn:
        conform = AsyncDbConform(async_connection=conn)
        result = await conform.compare([Product, Cart])  # same models as above
    await engine.dispose()
    if isinstance(result, ConformError):
        print("Compare failed:", result.messages)
    else:
        print(f"Plan has {len(result.steps)} step(s)")

asyncio.run(main())
```

### Example outputs

- **Empty database:** `compare()` might show steps like `Create table product`, `Create table cart`.
- **Schema matches:** `result.steps` is empty; your database is up to date.
- **Missing column:** If `cart` exists but lacks `quantity`, you might see `Add column quantity to cart`.

Use `result.sql()` to get the full DDL script as a single string.

### Applying changes

To compare and apply in one call, use `apply_changes()`. Same comparison as `compare()`, but it executes the DDL. (For async, use `await conform.apply_changes(...)`.)

```python
result = conform.apply_changes([Product, Cart])

if isinstance(result, ConformError):
    print("Apply failed:", result.messages)
else:
    print(f"Applied {len(result.steps)} step(s). Schema is conformant.")
```

Options: `commit_per_step=True` commits after each step (partial progress on failure); `log_file="path"` appends applied steps as JSON lines to a file.


## For Developers


### Local Installation
Create a virtual environment and install the package in editable mode:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate   # Windows
pip install -e ".[dev, async, postgres]"
```

### Running tests

From the project root:

```bash
dbconform test run
```

With the `[postgres]` extra and Docker or Podman, this starts a Postgres container, runs the full suite (SQLite + PostgreSQL), then stops it. Without Postgres, only SQLite tests run.

Other commands: `dbconform test check-container` (verify Docker/Podman), `dbconform test postgres up` / `dbconform test postgres down` (manual container lifecycle). See `tests/TESTS_README.md` for test organization.

### Installing in other projects

To use dbconform in another Python application:

- **Development (same machine):** From your other project, run `pip install -e /path/to/dbconform` or `uv pip install -e /path/to/dbconform`. Changes in the dbconform repo are reflected immediately.
- **Built wheel:** From the dbconform repo run `uv build` (requires `uv` and dev deps: `pip install -e ".[dev]"`). This produces a wheel in `dist/` (e.g. `dist/dbconform-0.1.0-py3-none-any.whl`). In your other project: `pip install /path/to/dbconform/dist/dbconform-0.1.0-py3-none-any.whl`.
- **Private index:** Upload the contents of `dist/` to your index; then `pip install dbconform --index-url https://your-index/simple/`.
