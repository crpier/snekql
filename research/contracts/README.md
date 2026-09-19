# Equivalent runtime contracts

Research for #358. Follow-up to the commerce study in #355. No package fixes.

## Conclusion

Both implementations reached the tested application contract, but the work landed
in different places. SQLAlchemy needed explicit validation, codecs, and connection
policy. snekql needed handwritten CHECK/default SQL and an additional integer-input
check. Its strict schema verifier still rejected the intended literal default.

That last point changes the previous conclusion. Literal defaults are not merely
awkward to scaffold in snekql. They work at runtime, but the current model cannot
express the expectation needed to make strict verification accept them.

The earlier SQLAlchemy timestamp failure was repairable with a custom type.
snekql's advantage here is supplied policy and less codec maintenance, not a
capability that SQLAlchemy lacks.

## Contract and evidence

An order has:

- integer price_cents in 0..9999999999;
- integer quantity in 1..2147483647;
- a database-generated status default of `pending`;
- a database-generated creation time, or an explicitly supplied aware timestamp,
  normalized to millisecond UTC.

Application inputs must reject bool, float, Decimal, and string values for the
integer fields. Explicit None is invalid rather than a default request. Integer
cents are a deliberate scope choice, not a substitute for the previous decimal
experiment. See `SPEC.md`.

Four runs cover SQLite and MariaDB with both libraries. Each run includes 16
application cases, ten baseline raw SQL probes, and two deliberately corrupted
schemas with ten raw probes each. Additional observations cover native snekql
boolean input, SQLAlchemy bulk writes, and default readback after schema changes.

All 64 application cases had the specified acceptance or rejection outcome after
adding the policies described below. That is narrower than proving the entire
implementations equivalent. Strict schema verification remains an unmet deployment
requirement, and raw storage differs across engines.

Successful writes commit through actual snekql transactions or SQLAlchemy
AsyncSession flush/commit. A separate transaction or ORM session reads the row.
The comparison does not mistake an identity-map value for database decoding.

## What each implementation required

| Task | snekql | SQLAlchemy |
|---|---|---|
| Bounds | Annotated int with Field bounds | BoundedInteger custom type, plus attribute validation |
| Reject bool as integer input | Separate input check before model construction | Pydantic strict-int validation in the custom type and attribute validator |
| UTC and milliseconds | UtcDatetime | UtcMillis custom type with backend-specific binding and decoding |
| MariaDB connection policy | Built-in runtime settings | Explicit connection event setting UTC and SQL mode |
| Database CHECKs | Literal migration SQL | CheckConstraint declarations |
| Literal status default | Migration SQL plus GenCol[str] with PENDING_GENERATION | server_default=text("'pending'") |
| Treat explicit None as invalid | Construction validation | Attribute validation; evaluates_none() also needed for bulk timestamp writes |
| Existing-schema verification | Built in, but cannot express this literal default or verify CHECKs | create_all is not verification; another verification/migration mechanism is needed |

These examples are visible in `sqlite_models.py`, `mariadb_models.py`,
`snekql_inputs.py`, and `sqlalchemy_models.py`. The SQLAlchemy connection event is
in `experiment.py`. Shared observation code is not part of the declaration-cost
comparison. No timings or numeric ergonomics scores were collected.

### snekql accepts bool intentionally

Direct construction with quantity=True stored and fetched integer 1 on both
engines, despite Field(strict=True). The retained `native_bool_quantity`
observation exercises the full runtime without the extra input check.

Source inspection explains why: integer-logical fields convert bool to int before
Pydantic validation, matching Python's bool-is-an-int type relationship. This is
intentional package policy, not an unexplained database coercion or an established
package defect.

Our stronger contract therefore requires `validate_integer_inputs()` before model
construction. That check also rejects float, Decimal, and string input and adds
the field name to the error. Bounds remain in the model. Calling the model directly
still permits bool, so applications must consistently use the input boundary.

### SQLAlchemy has more than one write path

Attribute validators provided early errors for ordinary object construction. The
BoundedInteger type repeated validation at binding so dictionary-based bulk writes
could not skip it. Bulk quantity=True raised StatementError wrapping Pydantic's
integer validation error.

The timestamp case needed another decision. Before adding evaluates_none(), a
bulk dictionary containing created_at=None omitted the column and received its
server default. The custom type never saw None. With evaluates_none(), it reached
the binder and was rejected. Ordinary object construction already rejected None.
The focused test demonstrated this failure before the example was corrected.

A missing required quantity still failed at ORM flush, whereas snekql rejected it
at construction. These examples use ordinary SQLAlchemy declarative models, not
its dataclass integration or a separate request DTO. Matching rejection timing
would require another design choice.

## UTC now agrees through the runtime

Both implementations read the explicit input
`2026-01-02 08:34:05.123456+05:30` back as an actual datetime:

```text
2026-01-02 03:04:05.123000+00:00
```

SQLAlchemy's custom type uses UTC text on SQLite and naive UTC DATETIME(3) at the
MariaDB driver boundary. Decoding restores an aware application value. Its
attribute validator normalizes the in-memory value too. snekql supplies that
behavior through UtcDatetime and its codecs.

Both also generated millisecond timestamps when omitted. These observations use
live clocks, so exact generated timestamps are not compared across runs. All
MariaDB connections used UTC; this round did not repeat the previous experiment's
foreign-session timezone shift.

## Defaults expose different object lifecycles

Before persistence, snekql's generated ID/status/time fields contain
PENDING_GENERATION. After insertion, the original pending object still contains
those sentinels. Fetching produces the values supplied by the database.

SQLAlchemy initially exposes None for those omitted fields. After flush and commit,
the original ORM object contains its generated values. This example uses
expire_on_commit=False so inspecting it does not trigger implicit async IO. The
independent new-session read confirms the stored values too.

Neither approach is inherently better. snekql makes unavailable values explicit
and keeps the pending object unchanged. SQLAlchemy updates the object for the
caller, but its lifetime and expiration settings become part of application code.

## The schema-verification gap is real

The hand-authored snekql migration installs both CHECKs and the literal default.
GenCol[str] with default=PENDING_GENERATION lets inserts omit status without
pretending the model declares its server expression. Runtime reads return
`pending`. Strict verify then reports:

```text
column 'status' differs: server default expected None, found "'pending'"
```

The corruption probes make the limits concrete:

1. Remove both CHECKs outside the migration chain. Zero quantity becomes legal.
   Migration-history verification still succeeds. Model verification returns
   exactly the same literal-default issue as before, with no CHECK-related issue.
2. Change the live default to `queued`. Migration-history verification still
   succeeds. Model verification reports the live literal as drift, but it cannot
   encode that `pending` was intended while `queued` was not. A fresh runtime
   insert reads back `queued`.

The checksums certify the recorded migration declaration, not that nobody changed
the live schema afterward. These limits agree with `docs/schema-drift.md`; they
are not newly established bugs.

Do not treat blanket policy="warn" as equivalent verification. It downgrades
other drift too. This contract needs a deliberate policy for unsupported schema
facts and separate behavioral/schema checks, or a future model capability.

SQLAlchemy's original metadata still knows its expected CHECKs and default.
Calling create_all after the same corruption neither repairs nor rejects the
existing table. Reflection exposes the altered schema, but comparing it is the
application's job here. This study did not implement Alembic or an equivalent
verification service, so it does not claim SQLAlchemy solves deployment safety.

## Raw SQL still has weaker guarantees

Both libraries' installed schemas rejected zero quantity, negative cents, both
upper-bound overflows, and explicit NULL status/time. External omitted status
received `pending`.

Both engines accepted SQL string '1' for integer quantity. MariaDB rounded raw
1.5 cents to 2 even with CHECKs and strict mode; SQLite STRICT rejected it.
SQLite accepted malformed timestamp text, while MariaDB DATETIME rejected it.
Application validation cannot make those SQL input behaviors identical.

## Updated ergonomic judgment

I would still choose snekql's supplied UTC policy over maintaining this custom
codec for an ordinary application. Its missing-field feedback and explicit
pending values also help. But its behavior is not simply "Pydantic strictness
plus SQL"; integer boolean normalization is an additional policy to learn.

SQLAlchemy made the database rules easier to declare. Getting equally strict
application behavior required understanding attribute events, bind processing,
bulk omission, result conversion, async expiration, and connection setup. That
work can be packaged into reusable types, but someone still owns it and its tests.

For snekql, intentional literal-default drift is the larger maintenance concern.
A common order default cannot currently participate in a clean strict verification
result. CHECKs also need tests outside that verifier. This is worth discussing as
a capability proposal separately from this research.

## Reproduce and review

```sh
uv run --with-requirements research/contracts/requirements.txt python -m research.contracts.experiment
uv run --with-requirements research/contracts/requirements.txt snektest tests research/contracts
uv run --with-requirements research/contracts/requirements.txt ty check
uv run --with-requirements research/contracts/requirements.txt ruff check .
uv run --with-requirements research/contracts/requirements.txt ruff format --check .
```

Requires local mariadbd, mariadb-install-db, and mariadb binaries. The runner owns
all database resources. SQLite uses temporary files; MariaDB uses temporary,
socket-only servers. No external database URL is accepted by the entry point.
Schema-corruption probes operate only on those disposable databases. MariaDB DDL
commits implicitly; this is not a transaction-rollback experiment.

Recorded environment: Python 3.14.2, SQLite 3.50.4, MariaDB 12.3.2, SQLAlchemy
2.0.43, Pydantic 2.13.5, aiosqlite 0.22.1, aiomysql 0.3.2, greenlet 3.5.1. The local
snekql checkout reports 0.7.0 and is based on main commit 4dcb71669a9a9dffb202595e7f14251ff76714c8.
It is not identical to the published 0.7.0 artifact. Comparator additions are pinned
in requirements.txt; project dependencies remain in uv.lock. Database binaries
are recorded, not provisioned by the experiment.

MariaDB uses InnoDB, utf8mb4_bin, enabled CHECKs, UTC, and the same five SQL-mode
flags used by snekql's runtime. SQLite raw connections enable foreign keys.
`results.json` records controls, full baseline/drift raw observations, errors,
Python types, installed schemas, and object states. `.sql` files contain literal
snekql migrations or SQLAlchemy CreateTable output. Live clocks and some Pydantic
function addresses make snapshots non-byte-reproducible.

Validation: 1356 tests passed, including 18 research checks. Typing and Ruff passed.
The sole root configuration change scopes a typing exception to SQLAlchemy's
Mapped/mapped_column declarations in this research file.

These are focused examples, not production-ready reusable policy types. Updates,
relationships, corrupted-row materialization, all bulk APIs, migration upgrades,
concurrency, latency, and driver/backend version matrices remain untested here.
