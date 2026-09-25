> Advanced continuation: [sixteen more matched class-body/dual operations](../paired_advanced/README.md),
> with an [updated assessment](VERDICT.md). Start with the new body.py/dual.py for joins, recursion, writes, and streaming.

> Nesting is dropped. The [native-baseline typing study](../dual_typing_parity/README.md)
> supplied the query-reuse experiment used by the advanced continuation.

# Three model approaches in the same twelve situations

Start with [dual.py](dual.py) and [body.py](body.py), side by side. The nested
version remains as a third control:

- **[dual.py](dual.py)**: input-first storage class, inherited complete Row class,
  generated-field refinements, explicit result link.
- **[nested.py](nested.py)**: complete outer row, independent nested Pending,
  explicit `__row__` link.
- **[body.py](body.py)**: one lifecycle-generic class, class-body `ReadType` witness,
  unchanged native constructors.

All three contain the same numbered sections in the same order. All main storage
classes and application functions are written in these files, not hidden behind
imports of earlier business examples. Tests and research adapters are separate.

All three use the original column vocabulary: `Col`, `FKCol`, and `JsonCol`.
The comparison-only `nested_sqlite.py` and `nested_mariadb.py` export aliases of the
existing research descriptors; they do not change their typing or runtime behavior.
Earlier studies keep their historical spellings. `GenCol` remains in the generic
approach because it expresses a state-dependent value, not a cosmetic rename.

Read **[VERDICT.md](VERDICT.md)** afterward for impressions and the recommendation.

Local, uncommitted research on `research/dual-model-situations`, based on main
`56dbc32`. Related [research issue #396](https://github.com/crpier/snekql/issues/396)
remains closed. No production changes, new dependencies, checker plugins, commits,
or publication. Query typing and query readability carry the most weight. Direct complete-value
construction and general model inheritance are minor concerns.

## Run

```sh
bash scratchpad/paired_situations/run.sh
```

This checks isolated typing callers, source edits, SQL and Scaffold comparisons,
consumer lint, actual ty navigation, SQLite behavior, and a disposable MariaDB
server. Logs and server data are under `.git/approach-situations/`.

For just the runnable SQLite examples:

```sh
uv run python -m scratchpad.paired_situations.tour
```

The tour reports the unsupported class-body mutual declaration rather than
silently substituting another representation. MariaDB execution and negative
constructor observations belong to the full runner, not the short tour.

## The twelve sections

| Section | Review focus | Evidence in this study |
|---|---|---|
| 01. Small model | Generated identity, nullable display name, explicit response | INSERT, optional lookup, missing lookup, exact result types |
| 02. Complete construction | Counter versus its input constructor | Missing/generated/sentinel challenges, runtime erasure, native `.construct()` hole |
| 03. Defaults and NULL | Required, nullable, Python default, SQL default | 168 runtime matrix cells, independent static cells, actual materialized defaults |
| 04. Ordinary FK | Nominal UserId/PostId, author join | Exact scalar projection, wrong-ID rejection, missing-parent execution error, nested target/domain guards |
| 05. Self FK | Comment with nullable parent | Root/reply insertion, SET NULL on parent deletion, matching function-local self-FK Scaffold |
| 06. Mutual FKs | Department manager and employee department | Nested and dual local declarations, early input construction, executed cascade; body declaration rejection; memoized early-binding failure |
| 07. Large model and edits | Twenty-field Order | Real INSERT, add field, nominal email type, changed status/default, deliberately stale edits |
| 08. Behavior | total, is_paid, receipt_key | Shared calculations on input, generated-ID method on complete values, rejected input method calls |
| 09. MariaDB fields | Decimal, UUID, datetime, JSON, Boolean, LongText, BLOB | Actual INSERT/SELECT/JSON extraction/generated timestamp, matching Product Scaffold, Decimal-FK schema controls plus a dual MariaDB FK join |
| 10. Generic helpers | Input-to-result and ready-query helpers | Exact query results, precise pair helpers, body nominal-helper erasure, exact body protocol alternative, native control |
| 11. Existing data | PATCH and settings upsert | Explicit NULL, omitted field preservation, existing digest18 preservation, fresh SQL default9 |
| 12. Navigation | Find storage from complete-value usage | Six actual ty definition requests; full and declaration-only isolated lint |

Methods are declared beside their fields in section 07. Section 08 shows their
shared implementation and a complete-value caller. This avoids monkey-patching
methods just to force all behavior into a later heading.

### Defaults matrix

The common Settings model has these seven tested value fields plus its key:

| Field | Logical type | Input default |
|---|---|---|
| timezone | str | Required |
| nickname | str or None | Required |
| enabled | bool | Python True |
| note | str or None | Python None |
| digest_hour | int | SQL 9 |
| locale | str or None | SQL NULL |
| created_at | UTC datetime | SQL current timestamp |

Each field is independently omitted, supplied as None, supplied with a valid
value, and supplied with the approach's omission sentinel. Both input and complete
constructors are exercised for all three approaches: 7 × 4 × 3 × 2 = 168 runtime cells.
Dual rows require generated values but inherit Python defaults. Nested complete
rows require every field; this is not the same constructor contract.

The proposed nullable-datetime SQL-NULL case is retained separately as
`nullable_datetime_default()` in all three files. Native `LiteralDefault(None)` rejects
that codec. Body fails at declaration; the dual and nested adapters fail at schema binding.
The successful common matrix therefore uses nullable text `locale`, not a silently
changed datetime contract. Neither result declaration fixes the native limitation.

### Source edits, not just a finished large declaration

[evolution.py](evolution.py) copies each actual review file into an isolated caller,
checks an unchanged control, applies each edit, runs ty, and executes construction.
[evolution.json](evolution.json) records source hashes, reviewable diffs, diagnostic
locations, exceptions, and rejection stages.

- Add a nullable cancellation_reason, including its input default.
- Change customer_email to a nominal EmailAddress, including the caller.
- Replace the draft status with queued and update the input default.
- Leave the caller, Pending contract, or default stale in separate challenges.

There are 22 observations including three unchanged controls and dual generated-
field additions with and without the necessary row refinement. A new nominal email
with an unchanged string caller rejects statically in all three approaches, but executes
successfully after erasure because NewType is not runtime validation.

The stale status default differs: native constructor typing rejects the body
model's stale literal at declaration-check time; nested `default()` returns Any
and misses it statically. Dual Text also returns Col[Any] and misses it. All three
reject the value during construction. Missing or
mismatched Pending field declarations also pass static checking but reject at
nested outer-class declaration.

## Deliberate asymmetries

The comparison preserves the applications' requirements, not an artificial claim
that these prototypes offer identical interfaces.

### Native operations versus bounded adapters

Body uses native Database, Transaction, verbs, storage, and codecs directly. The
only SQLite model change is the witness-only base from the earlier study.
[body_maria.py](body_maria.py) adds the corresponding witness-only MariaDB base.
Neither base imports the earlier constructor-hardening implementation.

Nested reuses the earlier row/input, storage, finalization, and query adapters.
Its Database facade hides command translation; native snekql still owns connections
and transactions. This is not another runtime or an ORM.

Dual reuses input-first pairing, inherited storage, and the same bounded query
adapter. Its SQLite namespace adds Blob to the dataclass-transform field specifiers;
its MariaDB namespace adds native Column Type capture and deferred row pairing.
No business fields are generated at runtime for the checker.

Important visible gaps shared by the independent adapters:

- The dual and nested transactions expose fetch_all, not the native optional-cardinality
  method. Its fetch_user uses a primary-key predicate and returns the sole row or
  None. This is not a general fetch-one implementation.
- General dual/nested UPDATE and DELETE are not implemented. The review file explicitly
  calls [gaps.py](gaps.py) or [dual_gaps.py](dual_gaps.py), which delegates to native verbs using string field
  names. Those assignments are not statically checked. PATCH additionally reads
  the row back, while body can use native UPDATE RETURNING.
- The dual/nested generic Write alias covers INSERT RETURNING only. The native body
  helper accepts the broader native Write contract.

These are prototype coverage gaps, not proofs that these declaration designs cannot support the
missing operations. They still count as work required before adopting this design.

### Inherited native limitations are not class-body regressions

The body model retains the native generated-sentinel constructor hole, unchecked
construction hole, instance/specialized-source runtime rejection, forward-mutual FKCol
rejection in the tested spelling, Decimal-FK precision metadata failure, and the
nullable-datetime SQL-default restriction.

Native controls remain in earlier research, rerun below. Two isolated original
controls here also distinguish result erasure in the new witness-only base from
existing frozen-assignment static acceptance in native models.

All three complete models are runtime-frozen. In the tested body/native declarations,
ordinary field assignment is accepted statically and rejected at runtime; dual and nested
assignment reject statically too. None proves deep immutability of
nested dictionaries.

## Evidence

- Original nested/body callers: **163 observations**: 75 capabilities, 65 rejections,
  20 accepted counterexamples, three unsupported contracts.
- Dual/body callers: **225 observations**: 100 capabilities, 99 rejections,
  19 accepted counterexamples, seven unsupported contracts. This repeats relevant
  controls from the first set; do not add the totals as independent discoveries.
- **22 source-edit observations**, including independent unchanged controls.
- **280 runtime tests**, including 168 default-matrix cells and **13 real MariaDB
  tests**. Query result differences have separate runtime checks.
- Seven matching scaffolds across all three approaches.
- Eight matching compiled SQL/ordered-parameter triples: four INSERT RETURNING
  cases, model SELECT, scalar SELECT, FK join, and settings upsert.
- Six actual ty definition requests, covering complete classes and inherited fields.
- All three full consumers and declaration-only consumers lint without unused-import
  allowances, future imports, or quoted result bases.

The new query probes cover source selection, exact results, owner scope, readiness,
nominal IDs, FKs, backend mixing, conflict writes, projections, joins, and helper
precision. Unsupported operations stay recorded rather than receiving Any fallbacks.
See [VERDICT.md](VERDICT.md) for the query-weighted interpretation.

Typing rejects require a clean control and located challenge diagnostics. A crash,
unresolved import, or unrelated error is not counted as a static guarantee.
Capabilities describe the observed interface; they do not establish full parity.

Evidence files:

- [cases.json](cases.json), [results.json](results.json): original paired callers.
- [dual_cases.json](dual_cases.json), [dual_results.json](dual_results.json):
  dual/body callers and the additional query comparison.
- [evolution.json](evolution.json): actual source edits and their consequences.
- [evidence.json](evidence.json): hashes, field counts, SQL, scaffolds, lint, version.
- [navigation.json](navigation.json): actual definition responses and target lines.
- `test_dual.py`, `test_nested.py`, `test_body.py`: application behaviors.
- `test_*_maria.py`: actual backend execution, including the dual Decimal FK join.
- `test_query_comparison.py`: differing join semantics, native source holes,
  exact protocol-based body insertion, and native tuple projection.
- `test_defaults.py`, `test_limits.py`, `test_dual_limits.py`: erased values,
  declaration/binding guards, and retained failures.

## Validation

The full three-way runner passes: 280 runtime tests, both typing sets, source edits,
SQL comparisons, consumer lint, navigation, and local ty/Ruff/format checks.
Repository ty, Ruff, formatting, and tracked diff checks also pass.
The existing native fast suite passes **1,127 tests in 24.34 seconds**.

## Bounds

This is not full native query parity, an exhaustive FK/backend matrix, a framework
integration test, or a performance/concurrency study. No alias/self-join expansion,
recursive queries, general model inheritance, client default factories, bulk-write
correlation, or migration planner was added. MariaDB cyclic migration behavior and
broader Decimal-FK behavior have earlier evidence. This comparison now also executes
a dual Decimal-FK join; body retains its native precision-metadata schema failure.

The primary deliverable is the set of readable application files. The counts
support those examples; they are not a score deciding which spelling should win.
