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

## Usage

Use modelsync as a library: define your models (e.g. SQLAlchemy or SQLModel), then compare them to the database. By default, only a plan is produced; apply only when you explicitly opt in.

```python
from modelsync import ModelSync

# With credentials (modelsync opens and closes the connection)
sync = ModelSync(
    credentials={"url": "sqlite:///./mydb.sqlite"},
    target_schema=None,  # omit for SQLite
)
plan = sync.compare([MyModel, OtherModel])
if not plan.steps:
    print("Schema is up to date.")
else:
    # Inspect plan.steps; apply only when you explicitly opt in.
    for step in plan.steps:
        print(step)
```

Or pass an existing connection you created: `ModelSync(connection=engine.connect(), target_schema="public")`.
