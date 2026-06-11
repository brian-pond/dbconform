"""
CHECK constraint expression helpers for DDL emission and stable comparison.

Fixes GitHub #12 Gaps 2–4: preserve outer parentheses, avoid corrupting ``(A) OR (B)``
during normalization, and wrap expressions so PostgreSQL parses them correctly.
"""

from __future__ import annotations

import re

def is_wrapped_in_parens(expression: str) -> bool:
    """
    Return True when the entire expression is wrapped in one balanced parenthesis pair.

    ``(A) OR (B)`` is not fully wrapped (the first ``)`` closes the outer group early).
    ``((A) OR (B))`` is fully wrapped.
    """
    expr = expression.strip()
    if not (expr.startswith("(") and expr.endswith(")")):
        return False
    depth = 0
    for i, ch in enumerate(expr):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth == 0 and i < len(expr) - 1:
            return False
    return depth == 0


def strip_outer_parens(expression: str) -> str:
    """
    Remove redundant outer parentheses only when they wrap the full expression.

    Unlike naive ``while startswith('(') and endswith(')')``, this does not corrupt
    ``(A) OR (B)`` into ``A) OR (B``.
    """
    expr = expression.strip()
    while is_wrapped_in_parens(expr):
        expr = expr[1:-1].strip()
    return expr


def format_check_expression_for_ddl(expression: str) -> str:
    """
    Return the inner CHECK body safe for ``CHECK ({body})`` DDL emission.

    Ensures top-level ``OR`` / boolean ``=`` between parenthesized subexpressions
    remain inside the CHECK predicate (GitHub #12 Gaps 2–3).
    """
    inner = expression.strip()
    if is_wrapped_in_parens(inner):
        return inner
    return f"({inner})"


def strip_redundant_comparison_parens(expression: str) -> str:
    """
    Remove optional parentheses around simple comparisons inside CHECK expressions.

    Only strips forms PostgreSQL reflection commonly adds, without breaking boolean
    ``(A) = (B)`` checks (GitHub #12 Gap 3/4).
    """
    expr = expression
    expr = re.sub(r"\((\w+ IS NULL)\)", r"\1", expr, flags=re.IGNORECASE)
    expr = re.sub(r"\((\w+ IS NOT NULL)\)", r"\1", expr, flags=re.IGNORECASE)
    expr = re.sub(
        r"\((\w+ = '[^']*')\)(\s+AND\s+)",
        r"\1\2",
        expr,
        flags=re.IGNORECASE,
    )
    expr = re.sub(
        r"(\s+AND\s+)\((\w+ = '[^']*')\)",
        r"\1\2",
        expr,
        flags=re.IGNORECASE,
    )
    return expr


def split_top_level_or(expression: str) -> list[str]:
    """Split a CHECK expression on top-level `` OR `` (outside parentheses)."""
    if " OR " not in expression.upper():
        return [expression]
    parts: list[str] = []
    depth = 0
    start = 0
    i = 0
    upper = expression.upper()
    while i < len(expression):
        ch = expression[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and upper[i : i + 4] == " OR ":
            parts.append(expression[start:i])
            i += 4
            start = i
            continue
        i += 1
    parts.append(expression[start:])
    return parts


def normalize_or_and_group_parens(expression: str) -> str:
    """
    Wrap AND branches in parentheses when an expression uses top-level OR.

    PostgreSQL reflection often omits branch parens around AND groups (GitHub #12).
    """
    parts = split_top_level_or(expression)
    if len(parts) <= 1:
        return expression
    wrapped: list[str] = []
    for part in parts:
        p = part.strip()
        if " AND " in p.upper() and not is_wrapped_in_parens(p):
            p = f"({p})"
        wrapped.append(p)
    return " OR ".join(wrapped)


def extract_check_body_from_pg_constraintdef(constraintdef: str) -> str:
    """Return the inner CHECK predicate from ``pg_get_constraintdef`` output."""
    expr = constraintdef.strip()
    if expr.upper().startswith("CHECK"):
        expr = expr[5:].strip()
    return strip_outer_parens(expr)


def normalize_check_expression_text(expression: str) -> str:
    """
    Canonicalize CHECK text for drift comparison (whitespace + safe outer parens).

    Applied before dialect-specific normalization (e.g. Enum ANY → IN).
    """
    return strip_outer_parens(" ".join(expression.split()).strip())
