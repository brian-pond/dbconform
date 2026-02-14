"""
SQL dialect-specific DDL generation (identifier quoting, CREATE/ALTER syntax).

See docs/requirements/01-functional.md (Identifiers and quoting) and
docs/technical/02-architecture.md.
"""

from modelsync.sql_dialect.base import Dialect
from modelsync.sql_dialect.postgresql import PostgreSQLDialect
from modelsync.sql_dialect.sqlite import SQLiteDialect

__all__ = [
    "Dialect",
    "PostgreSQLDialect",
    "SQLiteDialect",
]
