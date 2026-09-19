# Commerce schemas and ergonomics

Research for #355, independent of the relationship pilot in #353. No package
behavior changed. Start with this report, then `SPEC.md`, the model declarations,
and `results.json`.

## Preliminary conclusion

snekql provides more application-level policy in these examples: strict model
validation, explicit not-yet-generated values, UTC normalization, and rejection
of MariaDB decimal values that would otherwise be rounded. SQLAlchemy provides a
broader schema declaration vocabulary, but its familiar type names do not remove
SQLite or MariaDB storage limitations.

The important distinction is where a guarantee lives. A useful Python annotation,
a storage codec, and a database constraint are three different things. This round
exposed more gaps between them than the relationship pilot did.

## What ran

Three focused tables represent product prices, an alternative integer-cent
representation, and order quantity/status/creation time. They are not a complete
order-management schema; relationships were the previous pilot's subject.

Eight runs cover SQLite and MariaDB, both libraries, and idiomatic versus
storage-matched declarations. Each run records 16 raw SQL probes, nine
construction/encoding cases, unpersisted default values, and two database-rule
probes. Four additional probes change the MariaDB session timezone. Actual bound
timestamp writes/readback ran in seven configurations; SQLite SQLAlchemy's
DDL-only TEXT match explicitly skips that case. Four SQLAlchemy typed-price
readbacks contrast driver values with converted values.

No single pass count is appropriate. The specification includes desired commerce
rules that the initial declarations do not fully enforce. The findings below
identify those unmet requirements rather than labeling expected database behavior
as a package defect.

## Money

| Observation | snekql SQLite | SQLAlchemy SQLite, idiomatic | MariaDB, both libraries |
|---|---|---|---|
| Physical price type | STRICT TEXT | NUMERIC(10,2) | DECIMAL(10,2) |
| Sort prices 2 and 10 | 10, then 2 | 2, then 10 | 2.00, then 10.00 |
| Raw insert 1.239 | Preserves text | Preserves float 1.239 | Rounds to 1.24, with note 1265 |
| Raw insert 100000000.00 | Accepts | Accepts | Rejects out of range |
| Raw insert `banana` | Accepts | Accepts | Rejects |
| SUM of 0.1 and 0.2 | 0.30000000000000004 | 0.30000000000000004 | Exact Decimal 0.30 |

CanonicalDecimal means exact canonical representation, not fixed-scale money or
numeric text ordering. Our SQLite declaration added nonnegativity validation,
but not a two-decimal or precision bound. Its acceptance of 1.239 in Python is
therefore an unmet commerce requirement, not a violation of CanonicalDecimal's
contract. Extra application validation would be needed.

SQLite's NUMERIC declaration looks more like a money column, but it does not
enforce precision or scale. A particularly misleading observation: SQLAlchemy's
typed read of a raw stored 1.239 returned Decimal('1.24'). The database still held
1.239. A rounded Python result is not evidence of exact fixed-scale storage.

On MariaDB, both DDL variants let the database round 1.239 under
STRICT_ALL_TABLES. snekql's public encoder rejected that application value before
binding with `'price' decimal value does not fit DECIMAL(10, 2)`. Construction
alone accepted it; the storage-bound check happens at encoding. SQLAlchemy's
MariaDB Numeric bind processor passed the Decimal through unchanged.

### Integer cents

Both engines summed 10 and 20 to exactly 30 and sorted 200 before 1000. This is a
simpler storage option for a fixed minor-unit currency, but not a universal money
type. Currency, allowed range, rounding at conversion, tax calculations, and
aggregation overflow still need decisions.

The databases also differed on invalid cents. STRICT SQLite rejected raw 1.5;
ordinary SQLAlchemy SQLite INTEGER stored 1.5; MariaDB rounded it to 2. Our snekql
integer model rejected Decimal('1.5') during construction on both backends. Even
an INTEGER declaration is not universally an instruction to reject fractions.

## Timestamps

An aware input of `2026-01-02 08:34:05.123456+05:30` produced:

| Configuration | Typed readback after actual bound write |
|---|---|
| snekql SQLite public codecs + raw driver | 2026-01-02 03:04:05.123000+00:00 |
| snekql MariaDB public codecs + raw driver | 2026-01-02 03:04:05.123000+00:00 |
| SQLAlchemy SQLite DateTime(timezone=True) | 2026-01-02 08:34:05.123456, naive |
| SQLAlchemy MariaDB DateTime(timezone=True) | 2026-01-02 08:34:05, naive |
| SQLAlchemy MariaDB DATETIME(3) | 2026-01-02 08:34:05.123000, naive |

UtcDatetime did real work: it rejected naive inputs, normalized the offset to
UTC, and reduced precision to milliseconds. The SQLAlchemy timezone flag did not
supply that policy on either tested backend. This is not a claim about PostgreSQL
or about custom SQLAlchemy types and validators, which were not tested.

snekql's default emits millisecond UTC text on SQLite and CURRENT_TIMESTAMP(3)
with DATETIME(3) on MariaDB. The idiomatic SQLAlchemy defaults had second
precision. Matching those storage details was possible, but required SQLite
strftime SQL or the MariaDB-specific DATETIME constructor and default expression.

Raw SQLite TEXT accepted `not-a-date` and arbitrary timestamp formatting even
under STRICT. The logical annotation does not constrain another SQL writer.
Raw MariaDB DATETIME rejected the malformed date. All configurations rejected
explicit NULL creation time; ordinary status updates left creation time alone.

### UTC depends on the connection too

With a frozen MariaDB session clock, changing time_zone from +00:00 to +05:30
changed the generated DATETIME by five and a half hours in both libraries' DDL.
DATETIME plus CURRENT_TIMESTAMP does not enforce UTC independently of its writer.

This is not evidence that snekql's normal runtime has a timezone bug. Source and
`docs/engine-settings.md` show that its connection setup pins and verifies UTC.
The shifted-session probe deliberately bypassed that runtime, as an external SQL
writer might. SQLAlchemy applications need an equivalent connection policy if
UTC is their contract.

## Database rules and defaults

The snekql examples used `Annotated[..., Field(ge=0)]` for prices and `Field(gt=0)`
for quantities. Model construction rejected the invalid values, but raw SQL
accepted negative prices and zero quantities. Those annotations did not become
CHECK constraints.

A separate SQLAlchemy declaration added `CheckConstraint('quantity > 0')` and
`server_default=text("'pending'")`. Its emitted DDL rejected zero and filled
omitted status on both databases. The baseline snekql scaffold did neither.
Current exported snekql declarations and the server-default ADR provide no
corresponding general CHECK or literal server-default marker. The existing
migration mechanism can express these in hand-authored SQL. We did not modify
scaffold output to conceal that difference, and did not test a migration workaround.

Neither library's plain `default='pending'` supplied status to raw SQL. Before
persistence, however, the objects felt different: snekql's order already had
status `pending` and created_at `PENDING_GENERATION`; the ordinary SQLAlchemy
order exposed None for both. SQLAlchemy's normal column default applies during
insertion, not this constructor. This is an ordinary declarative model, not
SQLAlchemy's optional dataclass integration.

## Feel and ergonomics

These are author observations from implementing this experiment, not a user
study. No task timings, popularity comparisons, or numerical scores. Shared
runner code, configurable union annotations, and test-only typing accommodations
are experiment machinery, not counted as normal declaration burden.

| Quality | snekql | SQLAlchemy |
|---|---|---|
| Reading the domain intent | Col[UtcDatetime] and CanonicalDecimal name explicit policies | Numeric and DateTime name familiar SQL concepts, but some flags overpromise if read without dialect knowledge |
| First declaration | Small backend vocabulary limits choices | Ordinary Mapped declarations are compact; more choices become necessary for precision and backend behavior |
| Learning overhead | Pending/Fetched generics, GenCol, storage/logical split, and generation sentinel require explanation | Model declaration is simpler here, but constructor/default timing and non-validating annotations require explanation |
| Input feedback | Field-specific errors at construction or encoding | Constructor often accepts the input; the bind processor or database may object later |
| Error readability | Decimal overflow message is concise; nested Pydantic errors can expose function wrappers and memory addresses | SQLite float conversion error is short but less field-specific; database errors depend on the engine |
| Adding database policy | Positive Python values are easy; general CHECK and literal server-default rules leave the scaffold API | CHECK and server defaults fit directly into the schema declaration |
| Default readability | One default keyword is compact, but a marker changes its meaning from application to server | Separate default and server_default make the location of the guarantee easier to scan |
| Portability | Backend-specific storage choices are visible early | Shared declarations are convenient, but identical declarations do not promise identical storage semantics |

My preference from this task: snekql feels better when the central problem is
"accept a validated domain value and preserve its intended representation."
SQLAlchemy feels better when the central problem is "describe this database
schema, including unusual constraints and defaults."

Neither distinction is absolute. SQLAlchemy can gain input policies through
validators, custom types, or Pydantic; snekql can gain database rules through
migrations. Those routes add work in different places. The experiment did not
implement and measure their full cost.

## Product implications worth exploring

- A documented fixed-minor-unit money recipe would be more useful than presenting
  CanonicalDecimal as a universal money solution. Include the SQL ordering and
  arithmetic tradeoffs explicitly.
- UtcDatetime plus enforced UTC connections is a concrete strength worth showing
  with a before/after example. Call out millisecond precision as a choice.
- Document each guarantee as model validation, encoding, database DDL, or runtime
  connection policy. The same model currently carries several different contracts.
- General server-default markers and CHECK declarations look like meaningful
  schema-authoring opportunities. These are research candidates, not fixes in
  this PR or evidence that the library should become an ORM.
- Compare equivalent custom SQLAlchemy validation/types against equivalent
  snekql migration constraints before making a broad ergonomics recommendation.

## Reproduce and inspect

```sh
uv run --with-requirements research/commerce/requirements.txt python -m research.commerce.experiment
uv run --with-requirements research/commerce/requirements.txt snektest tests research/commerce/test_experiment.py
uv run --with-requirements research/commerce/requirements.txt ty check
uv run --with-requirements research/commerce/requirements.txt ruff check .
uv run --with-requirements research/commerce/requirements.txt ruff format --check .
```

Requires local mariadbd, mariadb-install-db, and mariadb binaries. All MariaDB
servers are temporary and socket-only. The runner accepts no external database
URL. SQLite databases are in memory. Every probe rolls back its rows; MariaDB
ID sequences may advance, but no probe relies on generated ID values.

Recorded environment: Python 3.14.2, SQLite 3.50.4, MariaDB 12.3.2, snekql 0.7.0,
SQLAlchemy 2.0.43, PyMySQL 1.1.2, Pydantic 2.13.5. Extra comparator dependencies
are pinned in requirements.txt; the project's dependencies remain in uv.lock.
Database binaries are recorded, not installed or pinned by the runner.

MariaDB uses InnoDB, utf8mb4_bin, STRICT_ALL_TABLES, NO_ENGINE_SUBSTITUTION, enabled
CHECK enforcement, and a fixed session clock. SQLite foreign keys are enabled.
SQLite's generated current time is not frozen. Live timestamps and Pydantic
function addresses make parts of results.json intentionally non-byte-reproducible.

Evidence includes:

- `.sql`: emitted scaffold/create_all statements, plus the separate rule task.
- `results.json`: controls, installed DDL, reflected columns, raw values and types,
  warnings, failures, construction stages, and bound readback observations.
- `*-columns.diff`: sorted reflected-column JSON comparison. Reflection metadata
  differences are not automatic behavioral mismatches.

The raw SQL track bypasses both validation systems. Construction/encoder probes
stop before driver execution and do not claim accepted values will necessarily
bind. Bound timestamp probes use public snekql encode/decode plus raw driver SQL,
or SQLAlchemy Core binding and result conversion. They do not exercise full
snekql transactions, ORM sessions, lifecycle hooks, or migration verification.
Matching SQLite TEXT DDL intentionally does not implement a SQLAlchemy codec.

Validation: 1211 tests passed via explicit paths, including six focused research
checks. Typing, Ruff lint, and formatting passed. No production code changed.
