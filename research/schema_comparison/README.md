# Schema comparison pilot

Research for #353. Start here, then inspect the `.sql` files and `results.json`.
No package behavior changed.

## Question and specification

Do independently declared CRUD table models install schemas that enforce the same
rules? SQLAlchemy is a comparator, not the oracle.

The pilot combines two scenarios in four tables:

- Users have generated integer IDs, required unique email, nullable nickname,
  and required status with an application default of `active`.
- A user has at most one profile. Profiles cannot reference missing users.
  Deleting a user deletes their profile.
- Teams have generated IDs and unique required names.
- Membership identity is the team/user pair. Both references are required.
  Aliases are unique within a team, but reusable in another team.
  Deleting a team deletes memberships. Memberships restrict user deletion.
  A separate user index supports reverse membership lookup.

`probes.py` spells out the independent SQL and expected outcomes. Sixteen probes
check this shared contract. Five diagnostic probes explore behavior where the
initial specification deliberately leaves policy open. Diagnostic outcomes are
not counted as passes or failures.

## Tracks

The idiomatic track uses explicit snekql generated-ID declarations and SQLAlchemy
`Mapped` declarations with `Integer`, `String(255)`, and `default="active"`.
These are selected examples of ordinary declarations, not a survey of users.
Foreign-key actions are explicit in both libraries. No ORM relationships or
sessions participate.

The matched track leaves snekql unchanged and adjusts SQLAlchemy to match its
storage policies:

- SQLite uses `Text`, `sqlite_strict=True`, and `sqlite_autoincrement=True`
  on the two generated-ID tables.
- MariaDB uses `BigInteger` and `String(255, collation="utf8mb4_bin")`.
  The controlled server supplies utf8mb4 and InnoDB. SQLAlchemy's DDL still
  depends on those server defaults; snekql emits charset and engine explicitly.

Matched means matching the measured database behavior, not identical DDL or
identical model-validation semantics. Cross-database equivalence is not assumed.

## Method and reproduction

```sh
uv sync --locked --group research
uv run --group research python -m research.schema_comparison.experiment
uv run --group research snektest tests research/schema_comparison/test_experiment.py
uv run --group research ty check
uv run --group research ruff check .
uv run --group research ruff format --check .
```

Requires local `mariadbd`, `mariadb-install-db`, and `mariadb` binaries. The runner
creates and cleans up four temporary socket-only MariaDB servers. It accepts no
production database URL. SQLite databases live in memory. Every probe starts
with freshly recreated tables and the same seed, including reset ID sequences.

Recorded environment: Python 3.14.2, SQLite 3.50.4, MariaDB 12.3.2,
snekql 0.7.0, SQLAlchemy 2.0.43, PyMySQL 1.1.2. Python dependencies are locked;
database binaries are local, not provisioned or pinned by this runner. Use the
recorded versions to reproduce this snapshot, or treat a different version as a
new experiment. These results do not establish MariaDB LTS compatibility.

SQLite foreign keys are explicitly enabled. MariaDB uses InnoDB, utf8mb4,
utf8mb4_unicode_ci as its database default collation, and
`STRICT_ALL_TABLES,NO_ENGINE_SUBSTITUTION`. Controls appear in every run record.

snekql DDL comes from public `scaffold`. SQLAlchemy DDL captures all
`metadata.create_all` statements through its mock engine. Both are replayed
through the same raw SQL connection, without bind processing or model validation.
Setup failures abort. Probe constraint/data errors are recorded; unrelated
operational errors abort rather than masquerading as constraint enforcement.

`results.json` contains emitted DDL, reflected columns/keys/indexes, installed
SQLite `sqlite_schema` or MariaDB `SHOW CREATE TABLE` output, controls, and probe
outcomes. SQLAlchemy reflection uses SQLite PRAGMAs and MariaDB schema inspection;
it is not an independent schema parser. Raw installed DDL provides a cross-check.
The `.diff` files compare reflected structures with sorted JSON object keys.
They retain names, list ordering, and reflection metadata; they are review aids,
not an automatic semantic-equivalence verdict.

## Findings

All 128 shared-contract checks passed across eight runs. Forty diagnostic
observations found the following differences. No defect established by this pilot.

| Behavior | snekql | SQLAlchemy idiomatic | Matched track |
|---|---|---|---|
| SQLite insert after deleting highest ID | Allocates 3 | Reuses 2 | Both allocate 3 |
| SQLite binary literal in email | Rejects under STRICT | Accepts in VARCHAR column | Both reject |
| MariaDB ID 2147483648 | Accepts with BIGINT | Rejects with INTEGER | Both accept |
| MariaDB `alice` versus `ALICE` unique email | Both allowed with binary collation | Duplicate under database default collation | Both allowed |
| 256-character email | SQLite accepts; MariaDB rejects | Same | Same |

### Different defaults and enforcement

The largest differences are storage policy, not relationship syntax. In this
pilot, snekql's MariaDB `Integer` means BIGINT and `Text` means VARCHAR(255) with
binary collation. SQLAlchemy's `Integer` means INTEGER, and an uncollated string
inherits the database's comparison rules. SQLite snekql tables are STRICT;
SQLAlchemy needs an explicit table option.

Neither library turns `default="active"` into a server default here. Raw inserts
omitting status failed in every run. This agreement is useful: model constructor
or insert defaults must not be mistaken for database guarantees.

### Equivalent behavior despite structural differences

snekql emits separate named unique indexes for email and team name. SQLAlchemy
emits inline UNIQUE constraints. Both reject the tested duplicates. Foreign-key
constraint names, supporting indexes, DDL ordering, quoting, and reflection
metadata also differ. MariaDB can add an index to support a foreign key even when
no corresponding CREATE INDEX statement appears in the emitted DDL.

SQLite reports primary-key nullability differently for snekql's inline
`INTEGER PRIMARY KEY` and SQLAlchemy's explicit `NOT NULL`. The tested composite
primary-key NULL insertion fails in both. Reflection flags alone are not a
behavioral verdict, especially for rowid aliases.

### Limits and next experiments

This is a pilot, not broad schema compatibility certification. It does not test
server timestamps, decimal rounding, JSON validity, check constraints, composite
foreign keys, nullable unique keys, Unicode/trailing-space collation edges,
updates of referenced keys, migrations, concurrency, or ORM cascades. No required
pilot declaration was unsupported. Do not extrapolate that result to those
unexamined capabilities.

Next: product catalog and orders, with independently specified decimal precision,
server defaults, timestamp representation, and invalid-value probes. Then add
multi-tenant composite foreign keys and document unsupported declarations without
silently replacing them with scalar references.

## Validation

- Experiment completed on both real database engines: eight runs, 168 probes.
- Explicit snektest paths: 1212 passed, including seven research runner checks.
- `ty check`, Ruff lint, and Ruff format checks passed.
- Bare `uv run --group research snektest` failed collection with `Empty module
  name`; explicit paths above run the package suite and research checks.
