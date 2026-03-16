"""
Integration tests: shrink-related skips and logging (PostgreSQL).

Traceability: docs/requirements/01-functional.md (Schema parity scope, allow_shrink_column)
and 02-non-functional.md (Observability: skipped_step events).
"""

from pathlib import Path

from sqlalchemy import create_engine, text

import dbconform


def test_length_shrink_postgres_skip_records_skipped_steps_and_logs(
    empty_postgres_db: tuple[str, str],
    capsys,
) -> None:
    """PostgreSQL: shrink blocked when allow_shrink_column=False, recorded as skipped_step."""
    url, schema = empty_postgres_db

    # Create table with longer VARCHAR than the model's SimpleTable.name (500 vs 255).
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE simple_table ("
                "id SERIAL PRIMARY KEY, name VARCHAR(500) NOT NULL, "
                "value DOUBLE PRECISION NOT NULL, count INTEGER NOT NULL)"
            )
        )
        conn.commit()
    engine.dispose()

    from tests.shared_models import SimpleTable

    conform = dbconform.DbConform(credentials={"url": url}, target_schema=schema)

    # Compare with allow_shrink_column=False: no ALTER step, but shrink recorded in skipped_steps.
    plan_or_err = conform.compare(SimpleTable, allow_shrink_column=False)
    assert not isinstance(plan_or_err, dbconform.ConformError)
    assert len(plan_or_err.steps) == 0
    assert len(plan_or_err.skipped_steps) >= 1
    assert any("shrink" in s.reason.lower() for s in plan_or_err.skipped_steps)

    # apply_changes should emit skipped_step JSON logs for the shrink.
    _ = conform.apply_changes(SimpleTable, allow_shrink_column=False)
    captured = capsys.readouterr().out.splitlines()
    assert any('"event": "skipped_step"' in line and "shrink" in line.lower() for line in captured)

