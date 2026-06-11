"""
Helpers for skipped-step reporting and conform finalization.

See docs/requirements/01-functional.md (Skipped steps).
"""

from __future__ import annotations

import json
import sys

from dbconform.errors import ConformError
from dbconform.internal.objects import QualifiedName
from dbconform.plan.skipped_types import SkippedCategory, SkippedSeverity
from dbconform.plan.steps import ConformPlan, SkippedStep


def make_skipped_step(
    *,
    description: str,
    reason: str,
    table_name: QualifiedName | None,
    category: SkippedCategory,
    severity: SkippedSeverity,
) -> SkippedStep:
    """Build a tagged :class:`SkippedStep`."""
    return SkippedStep(
        description=description,
        reason=reason,
        table_name=table_name,
        category=category,
        severity=severity,
    )


def blocking_skipped_steps(skipped: list[SkippedStep]) -> list[SkippedStep]:
    """Return skipped steps with error severity (harmful drift)."""
    return [s for s in skipped if s.severity == SkippedSeverity.ERROR]


def emit_plan_drift_warnings(
    plan: ConformPlan,
    *,
    emit_log: bool = True,
    log_file: str | None = None,
) -> None:
    """
    Emit warnings for skipped steps and extra tables (stderr + optional JSON log).

    Every skipped step is reported so operators can decide whether drift matters.
    """
    for s in plan.skipped_steps:
        table = f" on {s.table_name}" if s.table_name is not None else ""
        msg = (
            f"dbconform skipped step [{s.severity.value}] "
            f"{s.description}{table}: {s.reason}"
        )
        print(msg, file=sys.stderr)
        record = {
            "event": "skipped_step",
            "severity": s.severity.value,
            "category": s.category.value,
            "description": s.description,
            "reason": s.reason,
            "table": str(s.table_name) if s.table_name else None,
        }
        line = json.dumps(record) + "\n"
        if emit_log:
            sys.stdout.write(line)
            sys.stdout.flush()
        if log_file:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(line)

    if plan.extra_tables:
        names = ", ".join(str(t) for t in plan.extra_tables)
        print(
            f"dbconform warning: {len(plan.extra_tables)} extra table(s) in database "
            f"not in models: {names}",
            file=sys.stderr,
        )
        record = {
            "event": "extra_tables",
            "severity": SkippedSeverity.WARNING.value,
            "tables": [{"name": t.name, "schema": t.schema} for t in plan.extra_tables],
        }
        line = json.dumps(record) + "\n"
        if emit_log:
            sys.stdout.write(line)
            sys.stdout.flush()
        if log_file:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(line)


def finalize_plan_drift(
    plan: ConformPlan,
    *,
    emit_log: bool = True,
    log_file: str | None = None,
) -> ConformError | None:
    """
    Warn on all drift; return ConformError when error-severity skipped steps remain.

    Called after compare and before apply so harmful asymmetry fails before DDL runs.
    """
    if not plan.skipped_steps and not plan.extra_tables:
        return None

    emit_plan_drift_warnings(plan, emit_log=emit_log, log_file=log_file)
    blocking = plan.blocking_skipped_steps()
    if not blocking:
        return None

    return ConformError(
        target_objects=[
            ("skipped_step", f"{s.category.value}:{s.description}") for s in blocking
        ],
        messages=[
            f"[{s.severity.value}] {s.description}"
            + (f" on {s.table_name}" if s.table_name else "")
            + f": {s.reason}"
            for s in blocking
        ],
        plan=plan,
    )
