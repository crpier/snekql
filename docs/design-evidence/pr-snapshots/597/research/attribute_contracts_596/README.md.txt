# Evaluate Pydantic-owned attribute contracts for snekql reads

Research for [#596](https://github.com/crpier/snekql/issues/596), **2026-10-31**.
Baseline: `a1cf31d8dba78f9ddf0a2b687f5c188649c14391`. Continues #593 and its
[scalar typing proof](https://github.com/crpier/snekql/pull/595). **Not adopted
behavior, usage instructions or production implementation.** No new public
operation spelling, Logical Type, model state or raw result shape is selected.

## Assessment

**The direction is promising, but it is not a mechanical deletion of codecs.**
Pydantic can own acceptance, explicit conversion and successful Logical Types.
The probes demonstrate useful narrow storage contracts without a parallel
best-effort decoder. snekql must still own input-grammar selection, relational
Materialization, failure handling and storage compatibility. Distinguishing
application input from database representations is essential, not incidental.

Much of the current primitive/JSON path already delegates to Pydantic. The
potential gain is coherent operation policy, honest no-parsing results and
explicit native-value interpretation—not replacing every existing read with a
new abstraction layer.

The proposed whole-operation modes remain:

| Mode | Value policy | Intended static promise |
| --- | --- | --- |
| No parsing | Preserve driver values; do not call semantic parsers | Expected contract retained as unchecked provenance, not ordinary `T` |
| Declared parsing, likely default | Honor attribute contracts with `strict=None` | Logical `T` after successful validation |
| Strict parsing | Use `strict=True`; explicit validators still run | Same Logical `T`, narrower built-in acceptance |

No forced-`strict=False` mode, per-attribute override or aggregate design is added.
Strictness controls acceptance, not the output's Python type or SQL correctness.

## Evidence and reproducibility

**Executed:** 120 focused cases at Pydantic's public `TypeAdapter` seam: 57
explicit input/contract examples in both declared and strict modes, plus three
two-mode checks for explicit Boolean/date contracts and shared JSON payload
policy. Inputs are synthetic values, not fetched database rows. Assertions check
values, runtime types (including flat list elements) and fixed validation codes.

**Inspected, not executed:** current SQLite/MariaDB connection and driver source,
snekql Materialization, temporal schemas and named existing runtime tests. No
native connection, SQL, application Table Model, backend suite or benchmark ran.
The earlier Unparsed typing proof is separate; its tests are not transplanted or
counted as part of this run. No new consumer result-typing claim is established.

Environment: Python 3.15.0, Pydantic 2.14.0, pydantic-core 2.50.0, ty 0.0.84,
snektest 0.16.0, aiosqlite 0.22.1, aiomysql 0.3.2 and PyMySQL 1.2.0.

```sh
uv run snektest tests/research/test_attribute_contracts.py tests/research/test_pydantic_attribute_matrix.py
uv run ty check
uv run ruff check .
uv run ruff format --check .
```

Sources:
[explicit research contracts](../../tests/research/attribute_contracts.py),
[focused checks](../../tests/research/test_attribute_contracts.py), and
[full acceptance matrix](../../tests/research/test_pydantic_attribute_matrix.py).
These are research fixtures, not proposed library exports or a supported backend
compatibility matrix.

## What arrives from the database?

The following is **source-derived driver evidence**, not newly observed query
output. SQL storage affinity, column metadata, server settings and driver
conversion precede Pydantic. Strict validation cannot recover the original input
an independent writer supplied before the database/driver converted it.

| Storage / value | Current SQLite path | Current MariaDB path |
| --- | --- | --- |
| Integer | SQLite INTEGER normally produces Python `int` | PyMySQL integer decoders produce `int` |
| Boolean | INTEGER carries 0/1, not a Python `bool` contract | BOOLEAN's TINYINT representation is decoded as `int`, not automatically `bool` |
| Calendar date | TEXT normally carries text; no declared-type converters enabled here | Native DATE converter returns `date`; invalid/zero values can remain text |
| Date-time | Canonical TEXT carries text | Native DATETIME converter returns timezone-free `datetime` fields; invalid values can remain text |
| UUID | TEXT carries text, BLOB carries bytes | No UUID-object converter is installed; actual native UUID wire metadata/representation is not verified here |
| JSON | TEXT carries JSON text | Driver text/binary handling can yield text or bytes; do not assume a parsed payload |

The SQLite [connection adapter](../../snekql/sqlite/_buffered_connection.py#L38-L47)
does not supply `detect_types`; the installed `sqlite3.connect` signature reports
its default as zero. See also Python's
[SQLite/Python type mapping](https://docs.python.org/3.15/library/sqlite3.html#sqlite-and-python-types).
A TEXT value `"42"` in a probe does **not** prove a SQLite INTEGER column returns
that string: affinity may already have converted it. Imperfect mappings,
expressions and external data are separate sources of mismatches.

MariaDB [initialization](../../snekql/mariadb/runtime.py#L741-L774) does not install
custom converters. Installed `aiomysql/connection.py` defaults `conv` to PyMySQL's
`decoders`; `_read_row_from_packet` applies them after text decoding.
`pymysql/converters.py` maps TINY/integer types to `int`, DATE/DATETIME to their
native converters, and invalid dates to text. UUID representation remains a
native evidence gap, not an assumption that MariaDB supplies `UUID` instances.

## What the executed contracts establish

Representative results from the full synthetic matrix:

| Contract and input | Declared parsing | Strict parsing |
| --- | --- | --- |
| `int`, integer 42 | integer 42 | integer 42 |
| `int`, text `"42"` / integral float / integral Decimal | integer 42 | reject |
| `int`, fractional float or Decimal | reject, not truncate | reject |
| `int`, Boolean true | integer 1 | reject |
| `StrictInt`, text `"42"` | reject | reject |
| constrained age, integer 200 | reject range | reject range |
| `bool`, integer 1 / text `"yes"` | Boolean true | reject |
| `StrictBool`, integer 1 | reject | reject |
| explicit `SqlBool01`, integer 0/1 | Boolean false/true | Boolean false/true |
| explicit `SqlBool01`, 2, `1.0`, `"1"`, `"yes"`, NULL | reject | reject |
| `date`, canonical date text | `date` | reject |
| `date`, midnight timestamp text/native datetime | `date` | reject |
| explicit `CanonicalSqlDate`, canonical text or native date | `date` | `date` |
| explicit `CanonicalSqlDate`, compact/zero/timestamp text or native datetime | reject | reject |
| `AwareDatetime`, naive native datetime | reject | reject |
| `UUID`, canonical/hex text or 16-byte payload | `UUID` | reject |
| `Json[list[int]]`, JSON `[7]` | `[7]` | `[7]` |
| `Json[list[int]]`, JSON `["7"]` / `[true]` | `[7]` / `[1]` | reject |
| `Json[date]` / `Json[UUID]`, appropriate JSON string | logical value | logical value |

These are legitimate **different contracts**, not uniformly good/bad coercions.
Plain `bool` accepting `"yes"` is its declared Pydantic policy. An application
expecting only SQL 0/1 should choose a narrower contract rather than depend on an
unadvertised snekql repair rule. Output type correctness does not itself establish
that the application intended every representation the default contract accepts.

The two small research contracts make that alternative concrete:

- `SqlBool01`: explicitly map exact integers 0/1 to bool, then apply `StrictBool`.
  Reject unrelated text, integers and floats, even in declared mode.
- `CanonicalSqlDate`: explicitly parse only canonical `YYYY-MM-DD` text, then
  apply strict `date` validation; accept native dates but not native datetimes.

Both run their explicit parsing under `strict=True`. They do not weaken the
selected operation policy: that policy deliberately retains declared callbacks.
They need proper serialization/write/compatibility evidence before becoming
library types. No public names or global automatic selection are proposed.

There is a concrete current asymmetry: `Attr.decode` preconverts MariaDB native
Boolean values before strict logical validation, whereas SQLite INTEGER reads
reach the primitive adapter. Moving both to the declared contract makes that
representation policy visible; it does not mean preserving every current
acceptance rule. Such changes require a compatibility decision, not a claim that
the source-implied contrast is a newly reproduced backend defect.

## Reading an actual snekql mapping

This is an **unexecuted reading exercise**, using current declaration/query forms
and the research aliases. Assume `db` is the SQLite namespace and the imports,
`Age` contract and aliases are available; no model is instantiated or compiled:

```python
class Account[S = db.Pending](db.Model[S]):
    __row_type__: ClassVar[db.ReadType[Account[db.Row]]]

    id: db.Col[UUID] = db.Text(primary_key=True)
    age: db.Col[Age] = db.Integer()
    enabled: db.Col[SqlBool01] = db.Integer()
    birthday: db.Col[CanonicalSqlDate] = db.Text()
    tags: db.Col[Json[list[int]]] = db.Text()


query = db.select(Account).where(Account.age.gte(18))
```

The query still reads as SQL intent. The declaration exposes application
acceptance policy; generic `Integer`/`Text` storage alone cannot express it.
A whole-operation strict read would also tighten the plain UUID contract, not
just `age`. In the proposed direct-Python-input design, textual UUIDs would fail
until the application deliberately selects a suitable representation contract.
This is a design consequence demonstrated at the Pydantic seam, **not** a test of
new snekql behavior. The current implementation has not been changed.

The explicit Boolean/date aliases earn text by distinguishing useful application
concepts. Generating one alias for every storage/type pair merely to hide the old
codecs would not earn its place. Prefer standard types when their acceptance is
wanted; add curated contracts only for recurring, explainable rules.

## JSON: keep one payload policy, distinguish input grammars

The probes confirm that one `TypeAdapter(list[int])` can validate Python `[7]`
with `validate_python` and stored JSON `[7]` with `validate_json`. Passing JSON
text to `validate_python` of plain `list[int]` fails. Pydantic can own JSON parsing
and element validation together, including their JSON-specific strict rules.

This matters for **construction as well as reads**. Current snekql
[strips the field JSON marker for its logical adapter](../../snekql/storage.py#L1486-L1503).
The existing
[`json_marker_encodes_to_text_and_decodes_before_validation`](../../tests/sqlite/test_storage_codecs.py#L267-L299)
constructs an application payload from a dictionary and reads a dictionary from
stored text. Merely replacing every call with
`TypeAdapter(Json[dict[str, object]]).validate_python(...)` would reject the
already-logical constructor dictionary: that adapter expects JSON text.

Thus the deeper simplification is **one semantic payload contract with explicit
input-grammar entry points**, not necessarily one identical method call for
construction and reads. Possibilities remain to evaluate:

- retain storage/marker-directed dispatch to the payload adapter's
  `validate_json`, without pre-parsing into a second logical decoder;
- use a full explicit JSON read contract while separately retaining the
  application input contract.

Neither requires snekql to coerce individual JSON payload elements. Both require
an explicit account of annotation metadata, writes and NULL placement. Do not
silently select between them or introduce a mandatory whole-result BaseModel.

The executed matrix also distinguishes:

| Contract | Raw SQL NULL (`None`) | JSON document `null` |
| --- | --- | --- |
| `Json[list[int] | None]` | reject | accept as None |
| `Json[list[int]] | None` | accept | reject |

Current [JSON marker resolution](../../snekql/storage.py#L1002-L1039) and
[JSON decoding](../../snekql/storage.py#L1541-L1571) involve both marker stripping
and physical nullable shortcuts. The table is a **Pydantic** distinction, not a
claim current snekql preserves it. A redesign must choose deliberately rather
than flattening both forms through one physical `nullable` switch.

## Canonical storage and temporal meaning still matter

A permissive Pydantic `date` successfully parses midnight timestamp text as a
calendar date. That cannot repair SQL equality/order over a column mixing date
and timestamp strings. The research canonical-date contract rejects that form.
Current snekql already guards canonical date text in
[`_decode_primitive`](../../snekql/storage.py#L1587-L1611), with a named existing
[native test](../../tests/runtime/test_temporal_contracts.py#L284-L297) inspected,
not rerun. Parsing returned rows cannot detect every invalid row excluded by a
predicate or repair joins, uniqueness or comparison semantics across bad storage.

Accepted [ADR 0022](../../docs/adr/0022-explicit-temporal-meanings.md) and
[temporal values](../../snekql/_temporal.py#L17-L40) already separate UTC instants,
civil fields and zoned identity. Their strict Python schema requires nominal
instances; canonical wire text is accepted by their declared-mode/JSON paths.
Existing [strict temporal tests](../../tests/test_temporal_values.py#L125-L156)
assert nominal behavior; these were read, not executed here.

Native DATETIME is not automatically an instant: current
[`_decode_native_datetime`](../../snekql/storage.py#L1696-L1701) and
[MariaDB timestamp codec](../../snekql/storage.py#L2581-L2603) combine backend
fields with declared temporal meaning. Pydantic's `AwareDatetime` rejection of a
naive datetime is executed evidence that an ordinary type alone does not supply
that meaning. Any replacement must explicitly own field-to-instant/civil
interpretation, canonical text and precision; removing the codec does not settle
those questions.

An additional trade-off: putting SQL-input conversions directly into the shared
attribute annotation can broaden **constructor acceptance too**. A before-validator
runs before strict construction validation as well as strict reads. If nominal
application input must remain narrower, separate input/read contracts or explicit
phase context may be necessary. That is a substantive contract decision, not
ceremony for a checker. No temporal or construction policy is changed here.

## No-parsing results: structure is not value interpretation

No parsing should skip semantic validators, JSON parsing, temporal/Boolean
conversion and expression decode hooks. Driver conversions have already happened.
snekql must still check result width/cardinality, split source spans, identify
absent joined rows, preserve column order and close resources. A matched row with
all-NULL payload must remain distinct from an absent row; see current
[presence Materialization](../../snekql/_materialization_shape.py#L122-L159).

Scalar/tuple values can retain the original objects while a static marker records
the expected contract. Full model results are not solved by that scalar proof:

- [`decode_model_values`](../../snekql/_model_materialization.py#L72-L99) creates a
  normal Row Model and calls setters; these are not automatically raw-preserving.
- [Named projections](../../snekql/_named_projection.py#L83-L101) run final model
  validation. Constructing the same ordinary result type without it would falsely
  advertise invariants, and possibly execute other model hooks.
- An outer `Unparsed[RowModel]` preserves expected shape but is opaque to ordinary
  field access. Field-level markers or a distinct raw result view/state could
  retain more usability; neither is demonstrated. Whole-operation policy does
  not imply independently configurable per-field policy.
- NULL/presence narrowing, frozen fields, generated values, aliases and CTEs need
  their own consumer typing evidence. Do not generalize the nominal scalar marker
  to arbitrary models without that evidence.

Keep the goal of expected-type provenance; do not retreat to `Any` merely because
whole-row propagation is unresolved. Also do not claim that current
`validate=False` already implements this: JSON/native conversion and named
validation remain active on some paths.

## Failures and verification

Pydantic owns acceptance, but snekql must provide intentionally handleable,
redacted query failures. The matrix checks codes, not a new public error format.
Current [raw validation handling](../../snekql/_raw.py#L242-L272) and existing
[`validator_exceptions_have_safe_rendering`](../../tests/runtime/test_raw_validation_diagnostics.py#L28-L82)
show a useful precedent for suppressing input-derived values/messages and
normalizing custom errors. These native tests were not rerun.

The selected policy should be captured once per Execution Plan, not mutate
shared model/adapter configuration. Preserve the important failure distinctions:

- already-consumed stream batches do not disappear when a later batch fails;
- a RETURNING validation failure does not itself reverse an executed write;
- catching a mismatch is not a promise the transaction rolled back.

Existing
[`late_validation_failure_resets_per_execution`](../../tests/runtime/test_raw_validation.py#L339-L379)
and
[`multi_field_named_failure_keeps_write_effects_and_transaction`](../../tests/runtime/test_multi_field_decoding.py#L155-L183)
were inspected for those claims. No new streaming/transaction behavior is proved.

## Recommendation and next decisions

Continue the Pydantic-owned direction, with these responsibilities made explicit:

| Responsibility | Proposed owner |
| --- | --- |
| Value acceptance, constraints, explicit interpretation | Declared Pydantic contract |
| Python versus JSON input grammar, source identity and result structure | snekql's execution-local read plan |
| Meaning of native date-time fields / canonical storage rules | Explicit chosen contract and supported storage compatibility rules, not accidental generic coercion |
| SQL generation, serialization, wire parameters and precision | Deliberately designed write path; not eliminated by read changes |
| Failure redaction, operation context, stream/transaction lifecycle | snekql |
| Whether all stored data and SQL comparisons meet application requirements | Application Readiness evidence beyond validating returned values |

Before production integration, settle **(1)** JSON input/read contract selection,
**(2)** how strict reads deliberately accept storage forms without weakening
nominal construction, and **(3)** raw whole-row shape/typing and hook policy.
These are more valuable next decisions than inventing a generic parser helper.

Then scope native Transaction/driver tests for representative mappings and mixed
whole-model operations; this report has not run them. Retain targeted static
consumer tests for raw provenance and logical results. Performance needs separate
workload measurements, not an assumption that skipping Pydantic saves enough to
justify a parallel decoder. Aggregates, finer-grained policy and migration work
remain deferred.

## Validation record and limits

Both research-only custom contracts used red/green: `StrictBool` rejected integer
1 until its explicit before-validator was introduced; strict `date` rejected
canonical text until its explicit parser was introduced. Negative matrix cases
then covered unwanted nearby representations. Initial test collection required
explicit names for snektest `Param`; that was corrected before behavioral reds.
Ruff import/Decimal-spelling fixes were mechanical, not contract changes.

The focused run passed **120 cases in 0.02s**. Project ty, Ruff lint/format and
working/staged whitespace checks passed; 23 relative link targets, 19 source-line
bounds, 17 linked Python files and seven named existing-test references were
checked by text/AST without importing those modules. The checker excluded fenced
code before identifying Markdown links. No full
suite, native backend test, benchmark, consumer typing prototype, dependency or
production change is included. Static/style checks and synthetic values do not
certify native integration, backend parity or performance.

Installed driver source SHA-256 fingerprints, for the source-derived findings
above (not independently verified binary/build provenance):

```text
aiosqlite/core.py       7976abec1c6bd69433dd54a1083d2deb31a9a7f6f0c2f16d57355dcd2da8a482
aiomysql/connection.py  802b4bb35e53a79b481eadc864cb01a2a6b739b009b73aeccc8b696d98ccbc8f
pymysql/converters.py   f37107d6a14a2c54a5903010c976c750352655ac26bdcea3408aaafaac104dec
```
