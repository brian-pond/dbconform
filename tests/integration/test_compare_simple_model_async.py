"""
Async integration tests: AsyncDbConform.compare() and apply_changes() against a real database
(SQLite and PostgreSQL via empty_db_async).

Traceability: docs/requirements/01-functional.md — Database connection (async),
compare() / apply_changes(). Acceptance: schema (create tables, columns).
"""

from sqlalchemy.ext.asyncio import create_async_engine

import dbconform
from tests.shared_models import SimpleTable


async def test_async_compare_empty_db_returns_create_step(
    empty_db_async: tuple[str, str | None],
) -> None:
    """Async: model has table, DB does not — plan contains CREATE TABLE (01-functional)."""
    url, target_schema = empty_db_async
    conform = dbconform.AsyncDbConform(credentials={"url": url}, target_schema=target_schema)
    result = await conform.compare(SimpleTable)
    assert not isinstance(result, dbconform.ConformError), str(result)
    plan = result
    assert len(plan.steps) == 1
    assert "simple_table" in plan.sql()
    assert "CREATE TABLE" in plan.sql()


async def test_async_compare_with_connection(
    empty_db_async: tuple[str, str | None],
) -> None:
    """Async: caller passes async_connection; compare returns plan (01-functional)."""
    url, target_schema = empty_db_async
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        conform = dbconform.AsyncDbConform(async_connection=conn, target_schema=target_schema)
        result = await conform.compare(SimpleTable)
    await engine.dispose()
    assert not isinstance(result, dbconform.ConformError)
    assert len(result.steps) == 1


async def test_async_apply_changes_with_connection(
    empty_db_async: tuple[str, str | None],
) -> None:
    """Async: caller passes async_connection; apply_changes applies plan (01-functional)."""
    url, target_schema = empty_db_async
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        conform = dbconform.AsyncDbConform(async_connection=conn, target_schema=target_schema)
        result = await conform.apply_changes(SimpleTable)
    await engine.dispose()
    assert not isinstance(result, dbconform.ConformError), str(result)
    assert len(result.steps) == 1


async def test_async_apply_changes_then_recompare_parity(
    empty_db_async: tuple[str, str | None],
) -> None:
    """Async: apply_changes applies plan; recompare shows schema parity (01-functional)."""
    url, target_schema = empty_db_async
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        conform = dbconform.AsyncDbConform(async_connection=conn, target_schema=target_schema)
        result = await conform.apply_changes(SimpleTable)
    assert not isinstance(result, dbconform.ConformError), str(result)
    assert len(result.steps) == 1
    async with engine.connect() as conn2:
        conform2 = dbconform.AsyncDbConform(async_connection=conn2, target_schema=target_schema)
        recompare = await conform2.compare(SimpleTable)
    await engine.dispose()
    assert not isinstance(recompare, dbconform.ConformError)
    assert len(recompare.steps) == 0
