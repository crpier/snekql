# Concurrent updates and conflict detection

Research for #366, following #363. No production fixes or literal-default decisions.

## Conclusion

Neither library makes an unguarded read-modify-write safe across separate
transactions. Atomic arithmetic and an explicit revision predicate both worked
through the tested interfaces. SQLAlchemy also supplied optimistic checking for
ordinary ORM flush when configured with version_id_col, but that policy did not
extend to explicit UPDATE statements.

The surprising differences were connection and database policies. A SQLAlchemy
Session could report an active transaction while SQLite had not begun one. MariaDB
REPEATABLE READ produced different outcomes with innodb_snapshot_isolation on and
off. A library-only comparison would have attributed those effects incorrectly.

## What was tested

The counter starts at quantity=10, revision=1. Two independent callers each request
one decrement. Two successful requests must leave 8, otherwise a caller must receive
a detectable conflict. The unguarded example deliberately treats clean transaction
completion as request success and retains the returned rowcount for inspection.
This is an application policy, not a claim that the libraries promise concurrency
protection on every completed UPDATE.

Seven configurations produced 61 scheduled scenarios and seven no-op controls:

- SQLite snekql with its explicit deferred transactions;
- SQLite SQLAlchemy with explicit BEGIN, then its legacy aiosqlite transaction mode;
- MariaDB snekql and SQLAlchemy, each with InnoDB snapshot isolation on and off.

Each caller owns its own transaction or session. Both read quantity 10 before
caller A is allowed to write. A commits before B writes. Some cases close the read
transactions first; others deliberately keep both read transactions open. These
are deterministic interleavings that expose a race, not a stress test or a
measurement of how frequently that race occurs.

Barriers and events control order. There are no correctness sleeps. TaskGroup
cancels sibling workers on unexpected failure, and each schedule has a 15-second
outer deadline. Timeouts of that deadline abort rather than count as successful
conflict detection. Fresh reads use new transactions/sessions, not retained ORM
identity-map values.

## Separate read and write transactions

The two callers first read 10 and end their read transactions. Then A and B write,
in that order, each in a fresh transaction.

| Write strategy | Result in every configuration |
|---|---|
| Assign the previously read quantity minus one | Final 9, one decrement lost |
| Atomic quantity=quantity-1 | Final 8, both applied |
| Compare-and-swap using the previously read revision | Final 9; B reports conflict |

The atomic statement also increments revision and guards quantity>0. These runs
start at 10 and do not test exhaustion or negative-stock races. They prove the
specified two-decrement case, not every inventory invariant.

The tested snekql builder's assignment interface accepts Python values and
CurrentTimestamp, not arithmetic expressions. Its atomic path therefore uses
public raw SQL with a bound row ID. SQLAlchemy expresses the arithmetic through
its ordinary update expression. No unmerged expression implementation was imported.
The raw path bypasses snekql column codecs, which is unproblematic for these fixed
integer parameters but is an additional responsibility for other logical types.

Manual compare-and-swap worked through both libraries. It writes the new quantity
and revision only where the stored revision equals the observed one. The first
write returned 1 and the stale write returned 0. The research application translates
that zero into a conflict; snekql does not automatically raise one for this builder
operation. All competing writers must participate in the revision protocol.

## Keeping both read transactions open

A transaction alone was not a sufficient description of the protection provided:

| Configuration | Stale unguarded B write | Final quantity |
|---|---|---|
| SQLite snekql | SQLITE_BUSY_SNAPSHOT, code 517 | 9 |
| SQLite SQLAlchemy, explicit BEGIN | SQLITE_BUSY_SNAPSHOT, code 517 | 9 |
| SQLite SQLAlchemy, legacy mode | Completes without conflict checking | 9, lost update |
| MariaDB either library, snapshot isolation on | Record changed, code 1020 | 9 |
| MariaDB either library, snapshot isolation off | Completes without conflict checking | 9, lost update |

For SQLite, the legacy-mode control reported session_in_transaction=True but
driver_in_transaction=False after a table read. Explicit BEGIN changed the latter
to True and exposed the stale-snapshot write as an error. Legacy mode is observed
with this Python/aiosqlite/SQLAlchemy combination, not claimed for every version.
The explicit-BEGIN comparison is an added SQLAlchemy connection policy, not its
untouched default. WAL and timeout controls are shared across these cases.

The initial local MariaDB server reported innodb_snapshot_isolation=1. The first
runner treated error 1020 as unexpected and aborted. After retaining a focused
regression check, the study recognized that specific stale-snapshot error and added
the off-setting sensitivity comparison. Both settings still reported
REPEATABLE-READ. This is not evidence that one library has a stronger isolation
implementation; the server policy changed the outcome for both.

A revision predicate did not eliminate stale-transaction errors. With real SQLite
read snapshots or MariaDB snapshot isolation enabled, B's compare-and-swap also
received 517 or 1020. In the other configurations it returned zero rows instead.
Applications need to handle both kinds of conflict if they use this transaction
shape.

## Rowcount needs context

The no-op control updates the existing quantity 10 to 10:

| Configuration | Returned rowcount |
|---|---:|
| SQLite, either library | 1 |
| MariaDB snekql | 0 |
| MariaDB SQLAlchemy | 1 |

SQLAlchemy's MySQL/MariaDB dialect standardizes UPDATE rowcount as rows matched,
using FOUND_ROWS. snekql retains the driver's changed-row result here.

Consequently, the second stale assignment on MariaDB/snekql also returned 0.
That is an available hint that this particular decrement did not apply; the
unguarded example ignored it. It is not an automatic optimistic-concurrency
exception, and zero by itself does not mean a competing writer changed the row.
The no-op control returns zero without any competitor.

The compare-and-swap case avoids that no-op ambiguity: a match necessarily advances
revision. Its 1/0 distinction agreed across all configurations. The runner rejects
rowcounts outside the single-row 0/1 contract rather than guessing about success.

## ORM versioning is useful but scoped

The ordinary unversioned ORM objects also lost the second decrement. Adding:

```python
__mapper_args__ = {"version_id_col": revision}
```

made B's stale flush during commit raise StaleDataError. A had advanced revision
from 1 to 2; B still held revision 1. Final quantity was 9, with a detected conflict.
This worked in all four SQLAlchemy configurations, including legacy SQLite.

Using the same versioned mapper in Session.execute(update(...)) did not insert the
revision predicate or advance revision automatically. Both explicit stale updates
completed, leaving quantity=9, revision=1. The captured SQL retains that distinction.
Mapper versioning is therefore an ergonomic advantage for participating object
flushes, not blanket protection for every SQL statement associated with that model.

## Contention and explicit retry

The held-lock schedule is separate from the stale-snapshot schedule. Both callers
obtain and close their initial reads. A performs a guarded update but holds its
transaction open. B attempts its guarded update in a fresh transaction. A is not
released until B's attempt has failed and closed.

The recorded order was:

```text
A acquires write lock
B receives database error and exits its transaction
A commits
B rereads in a new transaction and retries
```

SQLite reported SQLITE_BUSY, code 5. MariaDB reported lock wait timeout, code 1205.
These are not the 517/1020 stale-snapshot errors. Both libraries recovered in a
fresh transaction after A committed.

The added application retry reads quantity=9, revision=2, recomputes the decrement,
and performs a new compare-and-swap. It does not resubmit the old assignment to 9.
Both the overlapping-read retry and held-lock retry ended at quantity=8,
revision=3 in every configuration. The second caller made at most two attempts.

The policy recognizes only the observed contention codes and compare-and-swap
conflicts, and never retries an error classified at commit. Unknown errors abort.
These units have no external side effects. The deterministic holder release is
not a production backoff algorithm, and the study says nothing about the safety
of replaying emails, payments, or an uncertain commit.

snekql's existing SQLite retry covers BEGIN IMMEDIATE acquisition, not statements
inside an already-read transaction. This study uses deferred transactions and
sets busy_max_retries=0. It does not evaluate that built-in immediate-mode policy.
The contention probes use snekql's builder path, whose chained driver exception
exposes the error code. Error-driven retry of the raw atomic path was not tested.

## Ergonomic observations

SQLAlchemy required less handwritten SQL for atomic arithmetic and less application
code for version-aware object flushes. It also required distinguishing object flush
from explicit DML and understanding the SQLite connection's actual BEGIN behavior.

snekql made revision checking explicit in the builder and returned the affected-row
count directly. The caller still owned conflict handling and full-transaction retry.
Its runtime already started the SQLite read transactions used in this comparison,
but atomic arithmetic required leaving the typed builder for raw SQL in this checkout.

The biggest lesson is to choose a write protocol and verify its connection policies.
Neither a Session object nor the phrase REPEATABLE READ fully described the observed
protection. These are implementation observations, not usability-study results or a
broad library ranking.

## Reproduce and review

```sh
export PYTHON_CONTEXT_AWARE_WARNINGS=1
uv sync --locked --all-extras
uv pip install --python .venv/bin/python --requirements research/concurrency/requirements.txt
uv run python -m research.concurrency.experiment
uv run snektest tests research/concurrency
uv run ty check
uv run ruff check .
uv run ruff format --check .
```

Requires local mariadbd, mariadb-install-db, and mariadb binaries. The runner creates
and owns temporary SQLite files and socket-only MariaDB servers. Its entry point
accepts no external database URL. Database binaries are observed, not pinned or
provisioned by the script.

Recorded environment: Python 3.14.2, SQLite 3.50.4, MariaDB 12.3.2, SQLAlchemy
2.0.43, greenlet 3.5.1, Pydantic 2.13.5, aiosqlite 0.22.1, aiomysql 0.3.2, and
PyMySQL 1.2.0. The local snekql checkout reports 0.7.0 but is based on main commit
8612010, not the published 0.7.0 artifact.

Both library pools allow two connections. SQLite uses WAL, foreign keys enabled,
and a deliberately shortened 100ms busy timeout rather than snekql's normal 5000ms.
MariaDB uses InnoDB, UTC, utf8mb4_bin, strict SQL mode, and a one-second InnoDB lock
wait. snekql's operation deadline is five seconds; schedule deadlines are separate.
Actual controls from two borrowed connections are retained, including distinct
MariaDB connection IDs and innodb_rollback_on_timeout=0.

Validation: 1646 tests passed, including 87 research checks. Typing and Ruff passed.
Comparator additions are pinned separately; no root dependency or lockfile changes.
CI installs those additions and uses explicit test paths. The only typing exception
is scoped to SQLAlchemy mapped_column declarations in this research file.

Read SPEC.md, then runtime.py for the two execution paths, schedules.py for overlap
and retry, and orm.py for retained-object flush behavior. results.json contains the
outcomes, event order, controls, and SQL. snekql builder statements are compiled for
inspection before execution; SQLAlchemy UPDATE statements are captured by its
public engine event, including ORM flushes. Raw atomic SQL is retained directly.
The seven .sql files contain installed table DDL.

Connection IDs and which reader reaches a barrier first can vary between runs.
No throughput, fairness, real-world race frequency, alternate backend-version matrix,
deadlock recovery, pessimistic row-locking API comparison, or serializable-isolation
claim is made. These examples are not a proposed production retry abstraction.
