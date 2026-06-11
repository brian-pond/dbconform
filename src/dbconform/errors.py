"""
Structured error for conform/compare failures.

Callers can determine which target objects failed and why. See
docs/requirements/01-functional.md (Error handling).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dbconform.plan.steps import ConformPlan


class ConformError(Exception):
    """
    Structured error returned when conform or compare fails.

    Inherits from Exception so callers can use raise X from conform_error
    or except ConformError. The API still returns this as a value; use
    isinstance(result, ConformError) to detect failures.

    target_objects: list of (object_type, identifier) e.g. ("table", "public.foo").
    messages: human-readable reason(s). One entry per object or a single summary.
    plan: when failure is due to blocking skipped steps, the built ConformPlan
        (steps, skipped_steps, extra_tables) for inspection without re-running compare.
    """

    def __init__(
        self,
        *,
        target_objects: list[tuple[str, str]] | None = None,
        messages: list[str] | None = None,
        plan: ConformPlan | None = None,
    ) -> None:
        self.target_objects = target_objects or []
        self.messages = messages or []
        self.plan = plan
        super().__init__(self._format())

    def _format(self) -> str:
        if not self.messages:
            return "ConformError(no messages)"
        return "; ".join(self.messages)

    def __str__(self) -> str:
        return self._format()
