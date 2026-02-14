# modelsync

Schema and model synchronization for keeping your database schema in sync with your SQLAlchemy or SQLModel definitions.

## Prerequisites

- Python 3.11+

## Setup

Create a virtual environment and install the package in editable mode:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate   # Windows
pip install -e ".[dev]"
```

## Installing in other projects

To use modelsync in another Python application:

- **Development (same machine):** From your other project, run `pip install -e /path/to/modelsync` or `uv pip install -e /path/to/modelsync`. Changes in the modelsync repo are reflected immediately.
- **Built wheel:** From the modelsync repo run `uv build` (requires `uv` and dev deps: `pip install -e ".[dev]"`). This produces a wheel in `dist/` (e.g. `dist/modelsync-0.1.0-py3-none-any.whl`). In your other project: `pip install /path/to/modelsync/dist/modelsync-0.1.0-py3-none-any.whl`.
- **Private index:** Upload the contents of `dist/` to your index; then `pip install modelsync --index-url https://your-index/simple/`.

## Running tests

From the project root, with the virtual environment activated:

```bash
pytest tests/
```

Run only unit tests or only integration tests:

```bash
pytest tests/unit/
pytest tests/integration/
```

See `tests/TESTS_README.md` for how tests are organized.

## Usage

Use modelsync as a library: define your models (e.g. SQLAlchemy or SQLModel), then compare them to the database. By default, only a plan is produced; apply only when you explicitly opt in.

### ModelSync: the three main entry points

**1. `ModelSync(...)` — set up the connection**

Create a `ModelSync` instance by passing either:

- **`credentials={"url": "sqlite:///./mydb.sqlite"}`** — modelsync will open the database, run your call, then close it. No need to manage the connection yourself.
- **`connection=engine.connect()`** — you provide an open connection; you are responsible for closing it when done.

For databases that use schemas (e.g. PostgreSQL), also pass **`target_schema="public"`** (or your schema name). For SQLite you can omit it.

**2. `compare(models)` — see what would change (dry run)**

Pass one model class or a list of model classes. modelsync compares their combined schema to the live database and returns a **plan** of steps (create table, add column, add constraint, etc.) without executing anything. Use this to inspect changes, log them, or generate a DDL script with `plan.sql()`. Returns a `SyncPlan` or a `SyncError` if something went wrong.

**3. `do_sync(models)` — apply the changes**

Same comparison as `compare()`, but **runs** the plan against the database. By default all steps run in one transaction: if any step fails, everything is rolled back. Returns the applied `SyncPlan` on success or a `SyncError` on failure. Optional: `commit_per_step=True` to commit after each step (partial progress on failure), or `log_file="path"` to append applied steps to a file.

---

Define one or more models and pass them (single class or a list) to `compare()` or `do_sync()`. The example below uses `compare()` to get a plan.

```python
from sqlalchemy import Column, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase

from modelsync import ModelSync, SyncError

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

sync = ModelSync(credentials={"url": "sqlite:///./mydb.sqlite"})
result_plan = sync.compare([Product, Cart])

if isinstance(result_plan, SyncError):
    print("Compare failed:", result_plan.messages)
else:
    if not result_plan.steps:
        print("Your target database is up to date.")
    else:
        for step in result_plan.steps:
            print(step)
        # result_plan.sql() returns the full DDL script for inspection or manual execution
```

**Using your own connection** — you open the connection and close it yourself:

```python
from sqlalchemy import create_engine

engine = create_engine("sqlite:///./mydb.sqlite")
with engine.connect() as conn:
    sync = ModelSync(connection=conn)
    result_plan = sync.compare([Product, Cart])
engine.dispose()
```

### Possible Outcomes

#### Scenario 1
If the target database is empty, printing each step might show:

```
Create table product
Create table cart
```

#### Scenario 2
If the database already matches your models, you'll see *Your target database is up to date.* and no steps.

#### Scenario 3
What if `cart` already exists in the database but is missing the `quantity` column? Then you might see:

```
Add column quantity to cart
```

To get the full DDL script as a single string, use `result_plan.sql()`.

### Applying the plan with do_sync()

To compare and apply the plan in one go (run the DDL against the database), use `do_sync()`. It uses the same comparison as `compare()` but executes the steps in a single transaction (all-or-nothing; rollback on failure). Returns the applied `SyncPlan` on success or `SyncError` on failure.

```python
result_plan = sync.do_sync([Product, Cart])

if isinstance(result_plan, SyncError):
    print("Sync failed:", result_plan.messages)
else:
    print(f"Applied {len(result_plan.steps)} step(s). Schema is now in sync.")
```

Optional: `do_sync(..., commit_per_step=True)` commits after each step so partial progress is kept if a later step fails. `do_sync(..., log_file="/path/to/sync.log")` appends applied steps as JSON lines to a file.

