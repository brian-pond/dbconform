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

Define one or more models and pass them (single class or a list) to `compare()`. modelsync compares the combined model schema to the actual database tables and returns a plan of DDL steps.

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
# To use an existing connection instead: `ModelSync(connection=engine.connect())`.
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

