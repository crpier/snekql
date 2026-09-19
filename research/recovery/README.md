# Updates, recovery, and corrupted-row reads

Research for #363, following #358. No production code changed. Literal-default
options remain undecided.

## What changed my understanding

The most consequential finding is about failed transactions, not validation syntax.
On both tested engines, catching a uniqueness error inside a snekql transaction
allowed the context to exit normally, but the earlier successful write did not
persist. Further operations inside that transaction were rejected.

SQLAlchemy distinguishes a failed ORM flush from a failed direct statement. After
the flush failure, commit raised PendingRollbackError. After the same uniqueness
violation through Session.execute, the session could read, write, and commit.
Calling all three cases "a failed write" would hide the important difference.

The second finding is about object state. A non-expiring ORM object can remain
out of sync with a successful database write. In the native MariaDB quantity case,
the retained object held 1.5 after commit, while a fresh session read integer 2.

## Study design

Eight configurations cover SQLite/MariaDB, snekql/SQLAlchemy, and native/validated
tracks. Each configuration observes:

- six partial updates, with independent readback;
- valid and invalid direct attribute assignment;
- successful commit, escaping uniqueness error, and caught uniqueness error;
- transaction/session recovery and retained object state;
- four external corruption attempts and subsequent reads.

Four additional SQLAlchemy observations isolate Session.execute from ORM flush.
There are 48 patch observations, 24 lifecycle scenarios, 16 assignment attempts,
32 corruption attempts, and four direct-statement scenarios. These are observations,
not 124 interchangeable assertions or a usability score.

`SPEC.md` defines desired behavior independently of either library. Native snekql
uses a positive-integer annotation and UtcDatetime; native SQLAlchemy uses ordinary
Integer and DateTime declarations. They do not supply equivalent application policy.

The validated track adds only:

1. A shared strict-positive-integer check before the patch write interface.
2. A SQLAlchemy TypeDecorator that validates quantity during result conversion.

There is no added ORM attribute validator, bind validator, or UTC codec in this
round. Direct assignment and direct statements can bypass the patch helper. This
track is intentionally narrower than the previous equivalent-contract experiment,
and does not establish equivalent guarantees for every write path.

Both schemas have primary keys, unique codes, nonnullable quantity/time, and a
nullable note. Neither has a quantity CHECK, so external corruption needs no
constraint disabling. Storage declarations remain idiomatic: SQLite STRICT versus
ordinary tables, BIGINT versus INTEGER on MariaDB, and backend-specific timestamp
storage. DDL and installed schemas are retained rather than claimed identical.

## Updates and assignment

Direct assignment to a fetched snekql model rejected both quantity=3 and quantity=0
with FrozenModelError. That is immutability, not successful domain validation.
Updates go through the query builder instead:

```python
await transaction.execute(
    db.update(Entry).set(Entry.quantity.to(2)).where(Entry.id.eq(1))
)
```

Ordinary ORM instances accepted both assignments. A mapped int annotation alone
does not enforce positive-integer input. Persistence then depends on flush,
column conversion, and database rules.

| Patch | Native snekql | Native SQLAlchemy |
|---|---|---|
| quantity=2, note omitted | Stores 2; preserves note | Same |
| note=None | Clears note | Same |
| quantity=None | Rejects while building update | Rejects at flush, database NOT NULL |
| quantity=0 | Rejects while building update | Stores 0 |
| quantity=True | Stores integer 1 | Stores integer 1 |
| quantity=1.5 | Rejects while building update | SQLite stores 1.5; MariaDB stores 2 |

The explicit patch policy rejected all four invalid quantity inputs before either
write interface. It does not make the models themselves enforce that policy.

Partial updates felt straightforward in both examples. snekql requires explicit
assignments and a WHERE clause. ORM assignment is shorter for an already-loaded
row, but the application must understand when flush occurs. These observations use
explicit flush to record error timing; SQLAlchemy can also flush automatically.

## Failure recovery

Each lifecycle scenario first changes quantity from 1 to 3. Failure scenarios then
try to change code='one' to the existing unique code 'two'. The caught-error case
attempts another read and an update to quantity=4 before exiting.

| Write path, both engines | Read/write after caught error | Exit/commit | Fresh quantity |
|---|---|---|---|
| snekql execute | Both rejected | Context returns normally | 1 |
| SQLAlchemy ORM flush | Both rejected | commit raises PendingRollbackError | 1 |
| SQLAlchemy Session.execute | Both succeed | commit succeeds | 4 |

When the original error escaped the transaction, both libraries left quantity at
1. Successful transactions left it at 3. Subsequent recovery writes persisted 5.

snekql required a new Transaction. Trying to use the closed one raised
TransactionClosedError. SQLAlchemy allowed reuse of the same AsyncSession after
explicit rollback. That is session reuse, not reuse of the failed SQL transaction.

Source inspection explains snekql's normal exit: the runtime marks a connection
unsafe on driver-operation exceptions and discards it at transaction exit instead
of committing. The independent read proves the earlier update did not persist.
The reuse diagnostic says "unsafe after a timed-out operation", although this
probe caused a uniqueness error, not a timeout. This deserves separate discussion;
this research does not change that behavior or its wording.

SQLAlchemy's direct-statement result is limited to these uniqueness errors on
SQLite and MariaDB. It says nothing about PostgreSQL, deadlocks, lost connections,
or whether an arbitrary error leaves a transaction usable. No savepoints were used.

## What the caller's object means

A fetched snekql model remains an immutable snapshot. It still held quantity=1
after an update committed quantity=3. Reading again produced a new model with 3.
Rollback did not mutate the old snapshot either.

The ORM write sessions deliberately used expire_on_commit=False, avoiding implicit
async IO when inspecting committed attributes. The successful quantity=3 update
left the retained ORM object at 3. Rollback still expired all five mapped attributes,
despite that setting. The experiment inspected expired_attributes and then awaited
session.refresh rather than accidentally loading attributes through synchronous
property access. Explicit refresh and independent reads returned quantity=1.

The native MariaDB fractional update exposes a separate limitation. The ORM object
held 1.5 after a successful commit, while the database rounded it to 2. A fresh
session saw 2. Non-expiring objects do not automatically reflect server coercions.
Our added patch policy rejected the input before this disagreement could occur.

This is a practical tradeoff rather than a general winner. Immutable snapshots make
staleness explicit but require refetching. ORM identity and mutation save some
caller work while adding expiration, refresh, and flush rules to understand.

## Corrupted-row reads

External SQL wrote quantity=0 and quantity=-1 successfully on all schemas. Native
snekql rejected both during model materialization. Native SQLAlchemy loaded them;
the added result validator made those ORM reads reject them too.

After a materialization failure, both libraries could still read the valid control
row in the same transaction/session. This differs from the failed-driver-operation
cases above. A read validation error did not poison the transaction in these probes.

Timestamp corruption had backend-specific outcomes:

- SQLite accepted malformed timestamp text. Both libraries rejected it on read.
- SQLite accepted a parseable timestamp without an offset. UtcDatetime rejected
  it on read; SQLAlchemy returned a naive datetime, including in the quantity-only
  validated track.
- MariaDB rejected malformed timestamp text during the external UPDATE. There was
  no malformed stored row to test, so those reads are marked not_attempted.
- MariaDB accepted the offset-free timestamp. That is its normal DATETIME wire
  representation. snekql decoded it as UTC; SQLAlchemy returned a naive datetime.
  The database cannot certify the timezone intent of an external writer.

The MariaDB malformed-write driver exception was OperationalError with code 1292,
not a Python datetime decode error. The runner classifies known data-error codes
and lets unrelated database failures abort rather than count as valid rejections.

## Reproduce

```sh
export PYTHON_CONTEXT_AWARE_WARNINGS=1
uv sync --locked --all-extras
uv pip install --python .venv/bin/python --requirements research/recovery/requirements.txt
uv run python -m research.recovery.experiment
uv run snektest tests research/recovery
uv run ty check
uv run ruff check .
uv run ruff format --check .
```

The warning flag is already required by the repository's raw-validation tests.
The first full-suite attempt without it reported 126 errors. With the documented
flag, all 1630 tests passed, including 71 research checks. Typing and Ruff passed.

Requirements pin the comparator additions, SQLAlchemy 2.0.43 and greenlet 3.5.1.
The existing uv.lock supplies project dependencies. Recorded versions include
Python 3.14.2, SQLite 3.50.4, MariaDB 12.3.2, Pydantic 2.13.5, aiosqlite 0.22.1,
aiomysql 0.3.2, and PyMySQL 1.2.0. The local snekql checkout reports version 0.7.0,
but is based on main commit 8612010, not the published 0.7.0 artifact.

Local mariadbd, mariadb-install-db, and mariadb binaries are required. They are
recorded, not provisioned or pinned. SQLite files and socket-only MariaDB servers
are temporary and owned by the runner; its entry point accepts no external URL.
MariaDB uses InnoDB, utf8mb4_bin, UTC, and the five SQL-mode flags recorded in
results.json. SQLite enables foreign keys. No constraints are disabled.

Setup inserts two fixed rows through external SQL before each scenario, outside
the transaction under observation. Fixed timestamps avoid clock comparisons.
This is not another insertion or timestamp-encoding fidelity study.

## Review and limits

Start with SPEC.md, then the declarations and policy.py. lifecycle.py keeps the
control-flow differences visible. corruption.py separates injection from reading.
experiment.py owns setup, patch observations, and artifact generation. results.json
retains outcomes, Python types, exceptions, controls, and schemas; the eight .sql
files contain emitted declarations.

Outside research/, changes are a typing exception scoped to SQLAlchemy's
mapped_column declarations and CI commands supplying the pinned comparator
requirements for testing and typing. A clean project-only environment cannot
import SQLAlchemy. Install comparator requirements into the environment rather
than relying only on uv run --with-requirements: in the clean-environment check,
Python saw that overlay but ty did not. CI uses explicit test paths, keeping optional research discovery
and local environment directories out of the default recursive scan. No root
dependency or lockfile changes. No previous research files or production modules
are imported or modified.

The examples do not test concurrency, network faults, savepoints, ambiguous commits,
all bulk/update expressions, large result sets, performance, or other driver versions.
The policies are research examples, not a proposed production abstraction. The next
design discussion should wait until we choose which observed costs matter in actual
applications.
