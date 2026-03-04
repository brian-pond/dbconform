# Transactions and Savepoints

dbconform runs DDL and data operations within a transaction. When the caller passes a connection that is already in a transaction (e.g. from `engine.begin()` or after `compare()` via `engine.connect()`), dbconform uses a **savepoint** instead of starting a new transaction. This document explains the concepts and what each supported database provides.

## True nested transactions vs savepoints

### True nested transactions (autonomous subtransactions)

A **true nested transaction** (or autonomous subtransaction) would allow:

- A child transaction to **commit independently** of its parent
- The child's changes to become **immediately visible** to other connections
- Parent and child to have **different outcomes** (e.g. child commits, parent rolls back)

This would require database support for multiple independent transaction contexts on a single connection. Standard SQL does not define this.

### Savepoints

A **savepoint** is a named mark within a single transaction:

- `SAVEPOINT name` — create a checkpoint
- `ROLLBACK TO SAVEPOINT name` — undo all work since that checkpoint (transaction continues)
- `RELEASE SAVEPOINT name` — discard the checkpoint, keeping changes made after it (still not on disk until outer transaction commits)

Savepoints are **hierarchically dependent**. If the outer transaction rolls back, all work—including changes that were "released" from inner savepoints—is undone. Nothing is durable until the outermost transaction commits. Savepoints provide partial rollback within one transaction, not independent transactions.

## Database support

The following table summarizes transaction features across five commonly used databases. This is important context for developers: the behavior of `connection.begin()`, `connection.begin_nested()`, and transaction-aware code differs across backends.

| Database   | True nested transactions | Transaction count | Savepoints |
|-----------|---------------------------|-------------------|------------|
| Oracle    | Yes (PRAGMA AUTONOMOUS_TRANSACTION) | No                | Yes        |
| SQL Server| No                        | Yes (`@@TRANCOUNT`) | Yes (SAVE TRANSACTION) |
| SQLite    | No                        | No                | Yes (since 3.6.8) |
| PostgreSQL| No                        | No                | Yes        |
| MariaDB   | No                        | No                | Yes        |

### True nested transactions

Only **Oracle** supports true nested (autonomous) transactions via `PRAGMA AUTONOMOUS_TRANSACTION`. A child block can commit independently; its changes are durable even if the parent rolls back. The other four databases do not offer this: inner "commits" are not independent, and a parent rollback undoes everything.

**SQL Server** allows nested `BEGIN TRAN`/`COMMIT`, but it is misleading: inner `COMMIT` only decrements `@@TRANCOUNT`; it does not persist changes. Any `ROLLBACK` aborts the entire transaction. So SQL Server does not support true nested transactions.

### Transaction count

**SQL Server** exposes `@@TRANCOUNT`, an integer reflecting how many transaction levels are open (number of `BEGIN TRAN` minus `COMMIT`). This makes it easy to check nesting depth. The other four databases do not have an equivalent system variable. They may allow inferring "am I in a transaction?" (boolean) via connection state or helper queries, but not "how many levels deep?" (integer). SQLAlchemy's `connection.in_transaction()` is a boolean used across all backends; it suffices for choosing `begin()` vs `begin_nested()`.

### Savepoints

All five databases support savepoints (named checkpoints for partial rollback). Syntax varies (`SAVEPOINT` / `SAVE TRANSACTION` / `RELEASE SAVEPOINT` / `ROLLBACK TO SAVEPOINT`), but the semantics are the same: changes remain part of the outer transaction until it commits; a parent rollback undoes everything. dbconform uses savepoints when the connection is already in a transaction.

### dbconform target databases

**None of the dbconform target databases (SQLite, PostgreSQL, MariaDB) support true nested transactions.** All three support **savepoints** only. Neither SQLite, PostgreSQL, nor MariaDB expose a transaction count variable.

## How dbconform uses this

When `apply_changes()` runs:

1. If the connection is **not** in a transaction: dbconform calls `connection.begin()` and runs all DDL steps in that transaction. On failure, the transaction rolls back.
2. If the connection **is** in a transaction: dbconform calls `connection.begin_nested()`, which emits `SAVEPOINT` under the hood. The DDL runs inside that savepoint. On failure, the savepoint rolls back; the outer transaction is unchanged. On success, the savepoint is released and the caller's outer transaction contains the changes.

This allows callers to use either:

- `engine.connect()` — dbconform commits the read transaction from `compare()`, then uses `begin()` for apply
- `engine.begin()` — dbconform uses a savepoint for apply; the caller's transaction context handles commit/rollback on context exit

Both patterns work because we never require true nested transactions; we only need savepoint semantics (partial rollback within a single logical transaction).

## References

- Oracle: [Autonomous Transactions](https://docs.oracle.com/en/database/oracle/oracle-database/21/lnpls/autonomous-transaction-pragma.html), [SAVEPOINT](https://docs.oracle.com/en/database/oracle/oracle-database/21/sqlrf/SAVEPOINT.html)
- SQL Server: [@@TRANCOUNT](https://learn.microsoft.com/en-us/sql/t-sql/functions/trancount-transact-sql), [SAVE TRANSACTION](https://learn.microsoft.com/en-us/sql/t-sql/language-elements/save-transaction-transact-sql)
- SQLite: [SAVEPOINT](https://sqlite.org/lang_savepoint.html)
- PostgreSQL: [SAVEPOINT](https://www.postgresql.org/docs/current/sql-savepoint.html), [Subtransactions](https://www.postgresql.org/docs/current/subxacts.html)
- MariaDB: [SAVEPOINT](https://mariadb.com/docs/server/reference/sql-statements/transactions/savepoint)
- SQLAlchemy: `Connection.begin_nested()` maps to savepoints
