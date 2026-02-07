"""
Dialect-specific DDL generation (identifier quoting, CREATE/ALTER syntax).

See docs/requirements/01-functional.md (Identifiers and quoting) and
docs/technical/02-architecture.md.
"""

from modelsync.dialect.base import Dialect
from modelsync.dialect.sqlite import SQLiteDialect

__all__ = [
    "Dialect",
    "SQLiteDialect",
]
