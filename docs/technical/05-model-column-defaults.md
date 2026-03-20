# Model column defaults and DDL (incident record)

This document records a **real defect** discovered when using dbconform with SQLModel/SQLAlchemy models, explains **why** it happened, and documents **how** dbconform fixes it. It is intended for maintainers and future readers who need context beyond a one-line changelog entry.

## Symptom (what callers saw)

When building DDL from models that define a **Python** `datetime.date` default on a `DATE` column (e.g. SQLModel `effective_from: date = Field(default=date(1970, 1, 1))`), PostgreSQL could reject the generated SQL with a **datatype mismatch** on the default.

Example of **broken** emitted DDL:

```sql
... "effective_from" DATE NOT NULL DEFAULT 1970-01-01
```

PostgreSQL does **not** treat `1970-01-01` as a date literal in this position. It parses it as the numeric expression `1970 - 1 - 1` (integer arithmetic), so the default’s type does not match `DATE` and the server raises an error.

## Root cause (why it happened)

dbconform’s model adapter maps each SQLAlchemy column to an internal `ColumnDef`, including a **`default` string** used when emitting `CREATE TABLE` / `ALTER ... SET DEFAULT`.

The extraction logic lives in `_default_expr` in [`src/dbconform/adapters/model_schema.py`](../../src/dbconform/adapters/model_schema.py). It considers both:

- `column.server_default` — intended for database-side defaults, and  
- `column.default` — Python-side defaults (`ColumnDefault` / `ScalarElementColumnDefault` in SQLAlchemy 2.x).

For any non-callable `.arg`, the implementation used **`str(default.arg)`** as the DDL fragment.

That works for some cases:

- Reflected columns and many `server_default=text('...')` cases attach a **SQLAlchemy `ClauseElement`** (e.g. `TextClause`) as `.arg`. For those, `str(...)` produces a **SQL-ready fragment**, including **single quotes** where needed (e.g. `'1970-01-01'`).

It fails for **bare Python scalars**:

- `default.arg` may be a **`datetime.date`** instance. In Python, `str(date(1970, 1, 1))` is `1970-01-01` **without** SQL string delimiters, which triggers the PostgreSQL parsing bug above.

So the mistake was **treating Python object `__str__` as SQL**, which is only safe for SQLAlchemy-rendered fragments, not for arbitrary Python values.

## Fix (what we changed)

1. **`ClauseElement` branch** — If `default.arg` is a `sqlalchemy.sql.elements.ClauseElement`, keep using **`str(default.arg)`** so reflection and explicit `server_default=text(...)` behavior stay unchanged.

2. **Python scalar branch** — Otherwise, treat `default.arg` as a Python value and map it to a **portable SQL literal fragment**:
   - `datetime.datetime` → single-quoted ISO (space separator between date and time; `'` doubled per SQL escaping rules where needed).
   - `datetime.date` → single-quoted `YYYY-MM-DD`.
   - `datetime.time` → single-quoted ISO time.
   - `bool` (checked before `int`, since `bool` is a `int` subclass in Python) → `TRUE` / `FALSE`.
   - `int`, `float` (finite only), `Decimal` → usual numeric text.
   - `str` → single-quoted with `'` → `''` escaping.
   - `enum.Enum` → recurse on `.value`.
   - `uuid.UUID` → single-quoted string form.
   - Anything else → **`None`** (omit DDL default) instead of emitting a misleading `str(value)`.

3. **Dialects** — PostgreSQL and SQLite already emit `DEFAULT {column.default}` (SQLite passes through `default_for_ddl` for timestamp aliases). No dialect change was required once `ColumnDef.default` carries a **valid fragment** (e.g. `'1970-01-01'` for a date).

## Design note: parity with reflected defaults

Model-side defaults after the fix often look like `'1970-01-01'`. PostgreSQL reflection may still report defaults in other equivalent forms (e.g. cast syntax). If strict **string equality** on `ColumnDef.default` ever false-positives as drift, normalization in the PostgreSQL dialect’s `normalize_reflected_table` (or semantic default comparison) would be a follow-up—not required for correctness of **new** DDL.

## Traceability

- **Requirements:** [docs/requirements/01-functional.md](../requirements/01-functional.md) — schema parity includes column defaults; DDL must be valid on real backends.
- **Implementation:** [`src/dbconform/adapters/model_schema.py`](../../src/dbconform/adapters/model_schema.py) — `_default_expr`, `_python_scalar_to_sql_literal`.
- **Tests:** [`tests/unit/adapters/test_model_schema.py`](../../tests/unit/adapters/test_model_schema.py) — defaults from models and `server_default` regression.

## Related reading

- [02-architecture.md](02-architecture.md) — adapters and internal schema flow.
