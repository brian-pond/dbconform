"""
PostgreSQL dialect: double-quoted identifiers, full ALTER support.

PostgreSQL supports ALTER COLUMN (type, nullability, default), ADD/DROP CONSTRAINT,
and schema-qualified objects. See docs/requirements/01-functional.md (Schema parity scope).
"""

from __future__ import annotations

import re

from dbconform.internal.objects import (
    CheckDef,
    ColumnDef,
    ForeignKeyDef,
    IndexDef,
    QualifiedName,
    TableDef,
    UniqueDef,
)
from dbconform.internal.types import CanonicalType
from dbconform.sql_dialect.base import Dialect


class PostgreSQLDialect(Dialect):
    """DDL generation for PostgreSQL."""

    @property
    def name(self) -> str:
        return "postgresql"

    def _quote(self, name: str) -> str:
        return f'"{name}"'

    def to_neutral_type(self, reflected_type: str) -> str:
        """
        Map reflected PostgreSQL type strings to neutral form.

        DOUBLE PRECISION, REAL → FLOAT; CHARACTER VARYING(n), varchar(n) → VARCHAR(n).
        """
        t = " ".join(reflected_type.split()).strip()
        u = t.upper()
        if u == "DOUBLE PRECISION" or u == "REAL":
            return "FLOAT"
        m = re.match(r"CHARACTER\s+VARYING\s*\(\s*(\d+)\s*\)", t, re.IGNORECASE)
        if m:
            return f"VARCHAR({m.group(1)})"
        m = re.match(r"VARCHAR\s*\(\s*(\d+)\s*\)", t, re.IGNORECASE)
        if m:
            return f"VARCHAR({m.group(1)})"
        return t

    def to_ddl_type(self, column: ColumnDef, *, pk_autoincrement: bool = False) -> str:
        """PostgreSQL: SERIAL/BIGSERIAL for autoincrement PK; else column.data_type_name."""
        if pk_autoincrement and column.autoincrement:
            type_upper = column.data_type_name.strip().upper()
            if type_upper in ("BIGINT", "INT8"):
                return "BIGSERIAL"
            return "SERIAL"
        return column.data_type_name

    def create_table_sql(self, table: TableDef) -> str:
        """Generate CREATE TABLE with columns and table-level constraints."""
        parts: list[str] = []
        pk_inline = (
            table.primary_key
            and len(table.primary_key.column_names) == 1
            and any(c.autoincrement and c.name in table.primary_key.column_names for c in table.columns)
        )
        for col in table.columns:
            pg_type = self.to_ddl_type(col, pk_autoincrement=bool(pk_inline and table.primary_key))
            seg = f"{self._quote(col.name)} {pg_type}"
            if pg_type not in ("SERIAL", "BIGSERIAL") and not col.nullable:
                seg += " NOT NULL"
            if pg_type not in ("SERIAL", "BIGSERIAL") and col.default is not None:
                seg += f" DEFAULT {col.default}"
            if pk_inline and table.primary_key and col.name in table.primary_key.column_names:
                seg += " PRIMARY KEY"
            parts.append(seg)
        if table.primary_key and not pk_inline:
            pk_cols = ", ".join(self._quote(c) for c in table.primary_key.column_names)
            parts.append(f"PRIMARY KEY ({pk_cols})")
        for u in table.unique_constraints:
            cols = ", ".join(self._quote(c) for c in u.column_names)
            name_part = f"CONSTRAINT {self._quote(u.name)} " if u.name else ""
            parts.append(f"{name_part}UNIQUE ({cols})")
        for fk in table.foreign_keys:
            cols = ", ".join(self._quote(c) for c in fk.column_names)
            ref_cols = ", ".join(self._quote(c) for c in fk.ref_column_names)
            ref = self.qualified_table(fk.ref_table)
            name_part = f"CONSTRAINT {self._quote(fk.name)} " if fk.name else ""
            parts.append(f"{name_part}FOREIGN KEY ({cols}) REFERENCES {ref} ({ref_cols})")
        for ck in table.check_constraints:
            name_part = f"CONSTRAINT {self._quote(ck.name)} " if ck.name else ""
            parts.append(f"{name_part}CHECK ({ck.expression})")
        body = ", ".join(parts)
        tbl = self.qualified_table(table.name)
        return f"CREATE TABLE {tbl} ({body})"

    def add_column_sql(self, table_name: QualifiedName, column: ColumnDef) -> str:
        """PostgreSQL supports ALTER TABLE ... ADD COLUMN."""
        pg_type = self.to_ddl_type(column)
        seg = f"{self._quote(column.name)} {pg_type}"
        if not column.nullable:
            seg += " NOT NULL"
        if column.default is not None:
            seg += f" DEFAULT {column.default}"
        return f"ALTER TABLE {self.qualified_table(table_name)} ADD COLUMN {seg}"

    def would_shrink(
        self,
        old_column: ColumnDef,
        new_column: ColumnDef,
    ) -> bool:
        """True if new column has a smaller length than old (VARCHAR/CHAR)."""
        old_len = self._parse_varchar_length(old_column.data_type_name)
        new_len = self._parse_varchar_length(new_column.data_type_name)
        return old_len is not None and new_len is not None and new_len < old_len

    def alter_column_sql(
        self,
        table_name: QualifiedName,
        old_column: ColumnDef,
        new_column: ColumnDef,
    ) -> str | None:
        """PostgreSQL supports ALTER COLUMN type, SET/DROP NOT NULL, SET DEFAULT."""
        tbl = self.qualified_table(table_name)
        qcol = self._quote(new_column.name)
        stmts: list[str] = []
        if old_column.data_type_name != new_column.data_type_name:
            ddl_type = self.to_ddl_type(new_column)
            stmts.append(f"ALTER TABLE {tbl} ALTER COLUMN {qcol} TYPE {ddl_type}")
        if old_column.nullable != new_column.nullable:
            if new_column.nullable:
                stmts.append(f"ALTER TABLE {tbl} ALTER COLUMN {qcol} DROP NOT NULL")
            else:
                stmts.append(f"ALTER TABLE {tbl} ALTER COLUMN {qcol} SET NOT NULL")
        if old_column.default != new_column.default:
            if new_column.default is None:
                stmts.append(f"ALTER TABLE {tbl} ALTER COLUMN {qcol} DROP DEFAULT")
            else:
                stmts.append(f"ALTER TABLE {tbl} ALTER COLUMN {qcol} SET DEFAULT {new_column.default}")
        if not stmts:
            return None
        return "; ".join(stmts)

    def add_primary_key_sql(
        self,
        table_name: QualifiedName,
        column_names: tuple[str, ...],
    ) -> str | None:
        """PostgreSQL supports ALTER TABLE ... ADD PRIMARY KEY."""
        cols = ", ".join(self._quote(c) for c in column_names)
        return f"ALTER TABLE {self.qualified_table(table_name)} ADD PRIMARY KEY ({cols})"

    def drop_column_sql(
        self,
        table_name: QualifiedName,
        column_name: str,
    ) -> str | None:
        """PostgreSQL supports ALTER TABLE ... DROP COLUMN."""
        return f"ALTER TABLE {self.qualified_table(table_name)} DROP COLUMN {self._quote(column_name)}"

    def drop_table_sql(self, table_name: QualifiedName) -> str:
        """Generate DROP TABLE for PostgreSQL."""
        return f"DROP TABLE IF EXISTS {self.qualified_table(table_name)}"

    def drop_unique_sql(
        self,
        table_name: QualifiedName,
        unique: UniqueDef,
    ) -> str | None:
        """PostgreSQL supports DROP CONSTRAINT for unique."""
        if not unique.name:
            return None
        tbl = self.qualified_table(table_name)
        return f"ALTER TABLE {tbl} DROP CONSTRAINT {self._quote(unique.name)}"

    def drop_foreign_key_sql(
        self,
        table_name: QualifiedName,
        fk: ForeignKeyDef,
    ) -> str | None:
        """PostgreSQL supports DROP CONSTRAINT for foreign key."""
        if not fk.name:
            return None
        tbl = self.qualified_table(table_name)
        return f"ALTER TABLE {tbl} DROP CONSTRAINT {self._quote(fk.name)}"

    def drop_check_sql(
        self,
        table_name: QualifiedName,
        check: CheckDef,
    ) -> str | None:
        """PostgreSQL supports DROP CONSTRAINT for check."""
        if not check.name:
            return None
        tbl = self.qualified_table(table_name)
        return f"ALTER TABLE {tbl} DROP CONSTRAINT {self._quote(check.name)}"

    def drop_index_sql(
        self,
        index_name: str,
        table_name: QualifiedName,
    ) -> str:
        """PostgreSQL: DROP INDEX; schema-qualify when table has schema."""
        if table_name.schema:
            schema_q = self._quote(table_name.schema)
            idx_q = self._quote(index_name)
            return f"DROP INDEX IF EXISTS {schema_q}.{idx_q}"
        return f"DROP INDEX IF EXISTS {self._quote(index_name)}"

    def create_index_sql(
        self,
        index: IndexDef,
        table_name: QualifiedName,
    ) -> str:
        """Generate CREATE [UNIQUE] INDEX for PostgreSQL."""
        uniq = "UNIQUE " if index.unique else ""
        cols = ", ".join(self._quote(c) for c in index.column_names)
        tbl = self.qualified_table(table_name)
        return f"CREATE {uniq}INDEX {self._quote(index.name)} ON {tbl} ({cols})"

    def _normalize_default_expr(self, default_expr: str | None) -> str | None:
        """
        Normalize reflected PostgreSQL default expressions for stable comparisons.

        PostgreSQL reflection often returns typed literal defaults as casts, e.g.
        ``'1900-01-01'::date``. Model-side defaults from SQLModel/SQLAlchemy Python
        values are represented as ``'1900-01-01'``. These are semantically equal and
        should not trigger repeated ALTER DEFAULT steps on re-apply.
        """
        if default_expr is None:
            return None
        expr = default_expr.strip()
        while expr.startswith("(") and expr.endswith(")"):
            expr = expr[1:-1].strip()
        literal_cast = re.match(
            r"^('(?:[^']|'')*')::(?:date|time(?:stamp)?(?:\s+with(?:out)?\s+time\s+zone)?)$",
            expr,
            re.IGNORECASE,
        )
        if literal_cast:
            return literal_cast.group(1)
        if re.match(r"^(true|false)$", expr, re.IGNORECASE):
            return expr.upper()
        return expr

    def normalize_reflected_table(self, table_def: TableDef) -> TableDef:
        """
        Normalize reflected table so it compares equal to model-side internal schema.

        - Columns with a sequence default (nextval) and integer-like type are rewritten
          to default=None, autoincrement=True, data_type_name=INTEGER|BIGINT so they match
          the model's representation and no spurious ALTER steps are emitted.
        - Implicit single-column UNIQUE constraints (e.g. habitat.name created from
          column unique=True) are given auto-generated names like habitat_name_key
          in PostgreSQL. Model-side UniqueDef for such constraints has name=None,
          so we strip the auto-generated name here to avoid drop/add churn on recompare.
        """
        INTEGER_LIKE = ("SERIAL", "INTEGER", "BIGSERIAL", "BIGINT", "INT8")

        new_columns: list[ColumnDef] = []
        for col in table_def.columns:
            if (
                col.default is not None
                and "nextval" in col.default
                and col.data_type_name.strip().upper() in INTEGER_LIKE
            ):
                type_upper = col.data_type_name.strip().upper()
                neutral_type = (
                    CanonicalType.BIGINT
                    if type_upper in ("BIGSERIAL", "BIGINT", "INT8")
                    else CanonicalType.INTEGER
                )
                new_columns.append(
                    ColumnDef(
                        name=col.name,
                        data_type_name=neutral_type,
                        nullable=col.nullable,
                        default=None,
                        comment=col.comment,
                        autoincrement=True,
                    )
                )
            else:
                neutral_type = self.to_neutral_type(col.data_type_name)
                # Non-SERIAL columns must not have autoincrement=True from reflection noise.
                new_columns.append(
                    ColumnDef(
                        name=col.name,
                        data_type_name=neutral_type,
                        nullable=col.nullable,
                        default=self._normalize_default_expr(col.default),
                        comment=col.comment,
                        autoincrement=False,
                    )
                )

        # Normalize unique constraint names for implicit single-column uniques.
        new_uniques: list[UniqueDef] = []
        table_name = table_def.name.name
        for u in table_def.unique_constraints:
            name = u.name
            if name and len(u.column_names) == 1:
                col = u.column_names[0]
                auto_name = f"{table_name}_{col}_key"
                if name == auto_name:
                    # Match model-side representation where name is None for column unique=True.
                    name = None
            new_uniques.append(UniqueDef(name=name, column_names=u.column_names))

        return TableDef(
            name=table_def.name,
            columns=tuple(new_columns),
            primary_key=table_def.primary_key,
            unique_constraints=tuple(new_uniques),
            foreign_keys=table_def.foreign_keys,
            check_constraints=table_def.check_constraints,
            indexes=table_def.indexes,
            comment=table_def.comment,
        )


def try_connect_to_postgres(url: str, timeout: float = 5.0) -> tuple[bool, str | None]:
    """
    Try to connect to Postgres at url (postgresql:// or postgresql+psycopg://),
    run SELECT 1 to validate auth and database. Returns (True, None) on success;
    (False, error_message) on failure. Requires psycopg; returns (False, 'psycopg not installed')
    if missing.
    """
    try:
        import psycopg
    except ImportError:
        return (False, "psycopg not installed")
    conninfo = url.replace("postgresql+psycopg://", "postgresql://", 1)
    try:
        with psycopg.connect(conninfo, connect_timeout=timeout) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return (True, None)
    except psycopg.OperationalError as e:
        return (False, str(e).strip())
    except Exception as e:
        return (False, str(e).strip())
