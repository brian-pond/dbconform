"""
Structured error for conform/compare failures.

Callers can determine which target objects failed and why. See
docs/requirements/01-functional.md (Error handling).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ConformError:
    """
    Structured error returned when conform or compare fails.

    target_objects: list of (object_type, identifier) e.g. ("table", "public.foo").
    messages: human-readable reason(s). One entry per object or a single summary.
    """

    target_objects: list[tuple[str, str]] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        if not self.messages:
            return "ConformError(no messages)"
        return "; ".join(self.messages)
