# Concurrent decrements

Research for #366. No package fixes or changes to the literal-default design.

## Confirmed interfaces

Real snekql transactions/builders/raw statements and SQLAlchemy sessions/statements;
two independent callers; fresh reads; affected-row results and explicit retry policy.
The user approved the proposed concurrency investigation through these interfaces.

## Oracle

Initial quantity 10, revision 1. Each caller requests one decrement. Two successful
requests must leave quantity 8. Otherwise a caller must receive a detectable conflict.
Two apparent successes leaving 9 are a lost update. A returned rowcount by itself is
not proof of concurrency protection; record a no-op UPDATE control.

## Schedules

- Detached reads: both callers read 10 and end their read transactions before either
  writes. Caller A commits first, then B writes its stale value. Compare unguarded
  assignment, atomic SQL arithmetic, and revision-based compare-and-swap.
- Overlapping read transactions: both read 10 while transactions remain open; A
  commits, then B attempts its update. Compare unguarded assignment and revision
  checking, with and without a bounded full-transaction retry.
- Held lock: both snapshots are collected first. A writes and holds the lock. B
  attempts a guarded update until the database reports contention. Only then may A
  commit. B retries once in a fresh transaction, rereading and recomputing.
- SQLAlchemy ORM version counter: ordinary flush of two retained stale objects;
  compare with explicit UPDATE, which does not inherit mapper version checking.

Barriers and events establish ordering. No timing sleeps establish correctness.
Each schedule has an outer deadline; timeout or unexpected driver errors abort the
study rather than count as detected conflicts. This is controlled interleaving, not
stress testing or a probability estimate for races.

## Controls

SQLite WAL, two connections available per library pool, bounded busy wait; the
matched SQLAlchemy track explicitly begins read transactions. Observe SQLite's
legacy SQLAlchemy/aiosqlite transaction behavior separately. snekql's SQLite
BEGIN IMMEDIATE retry is outside this deferred-transaction experiment.

MariaDB InnoDB, REPEATABLE READ, UTC, utf8mb4_bin, strict SQL mode, bounded InnoDB
lock wait. The initial local server reported innodb_snapshot_isolation=ON; retain
both explicitly enabled and disabled configurations. Error 1020 is an observed
stale-snapshot conflict, distinct from a lock wait timeout. Inspect actual controls and retain relevant emitted SQL and error codes.

Atomic arithmetic uses snekql's public raw statement because the tested query
builder does not expose arithmetic assignments. SQLAlchemy uses update expressions.
Do not import unmerged expression work or patch the library. Retry policies belong
to the example application and run only after known contention or revision conflicts.

No serializable isolation claim, deadlocks, pessimistic row-locking comparison,
network failure, uncertain commit, backoff tuning, fairness, throughput, or automatic
retry of external side effects. No overall library ranking.
