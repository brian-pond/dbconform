from io import StringIO

from dbconform.internal.objects import QualifiedName
from dbconform.plan import (
    AlterTableStep,
    ConformPlan,
    SkippedStep,
)


def test_conform_plan_summary_includes_counts_and_details() -> None:
    """ConformPlan.summary() includes counts, step descriptions, extra tables, and skipped reasons."""
    table = QualifiedName(schema="public", name="t")
    plan = ConformPlan(
        steps=[
            AlterTableStep(
                description="Alter column name on public.t",
                sql='ALTER TABLE "public"."t" ALTER COLUMN "name" TYPE VARCHAR(255)',
                table_name=table,
            )
        ],
        extra_tables=[QualifiedName(schema="public", name="extra_t")],
        skipped_steps=[
            SkippedStep(
                description="Alter column name on public.t",
                reason="Column shrink blocked: allow_shrink_column=False",
                table_name=table,
            )
        ],
    )

    text = plan.summary()
    assert "ConformPlan:" in text
    assert "1 steps" in text or "1 step" in text
    assert "extra_t" in text
    assert "shrink" in text.lower()
    assert "Alter column name on public.t" in text


def test_conform_plan_print_summary_writes_to_file_like() -> None:
    """ConformPlan.print_summary() writes the same content to the given file-like object."""
    table = QualifiedName(schema=None, name="t")
    plan = ConformPlan(
        steps=[
            AlterTableStep(
                description="Alter column name on t",
                sql='ALTER TABLE "t" ALTER COLUMN "name" TYPE VARCHAR(255)',
                table_name=table,
            )
        ],
        extra_tables=[],
        skipped_steps=[],
    )

    buf = StringIO()
    plan.print_summary(file=buf)
    output = buf.getvalue()
    assert "ConformPlan:" in output
    assert "Alter column name on t" in output

