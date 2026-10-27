# First assessment: trustworthy query results

**Status:** Source/existing-test assessment, 2026-10-27; no behavior change or new
runtime proof. Tracking: #590. Follows the maintainer's purpose discussion and
[working design brief, draft #589](https://github.com/crpier/snekql/pull/589).

**Baseline:** `3ed75324bbb12b189470f296e55faddf63d72b5b` (`origin/main` when this
assessment started). Source line references below describe that revision.
Draft #589 remains unmerged; the brief is not transplanted into this branch.

## Main finding

The current architecture already supports much of the desired identity:
explicit queries, runtime value validation, separate cardinality checks, typed
Rows, unchecked-read widening and shared SELECT/RETURNING decoding.

The first policy gap is more specific than "there is no type safety":

> Producing a value of the advertised Python type and rejecting an unexpected
> stored representation are different guarantees. Today, "validated" does not
> uniformly mean "no implicit coercion."

- Column construction uses strict logical validation with explicit exceptions.
  Ordinary fetched values deliberately use lax decoding.
- Named results validate strictly **after** their columns have decoded; strict
  final validation cannot establish that an earlier conversion was allowed.
- Raw result contracts intentionally use normal Pydantic behavior. Existing tests
  explicitly expect numeric-string coercion, supplied defaults and ignored extras.
- Native expressions can already require exact result types. Numeric aggregates
  have another policy: normalization independent of source-value constraints.

**Recommendation:** define permitted stored representations and conversions before
returning to constructor/default syntax. Do not equate tightening one Pydantic
call with solving the whole result contract.

## Evidence and limits

This is inspection of source, usage documentation and existing test assertions,
not a fresh runtime certification. No models, templates, factories, queries,
databases, benchmark tasks or test modules were executed or imported for this
assessment. Existing tests cited below were read, **not rerun**. Source-implied
counterexamples are labeled separately from assertions already present in tests.

Two questions guide the assessment:

1. **Result shape:** does successful Materialization produce the promised Python
   type and applicable constraints?
2. **Acceptance policy:** which wire values may become that result, through which
   declared codecs, normalizations or application validators?

A conversion can produce a type-correct result while violating the desired
acceptance policy. Conversely, rejecting all conversions would break legitimate
storage decoding. Neither question proves that SQL answered the business question
or that every underlying row satisfies a model contract: SQL may aggregate,
filter or convert data before Python ever sees it.

## Current read paths

| Path | Source observation | Consequence |
| --- | --- | --- |
| Table Model and ordinary scalar/tuple columns | [`Attr.decode`](../../snekql/storage.py#L1347-L1393) and [`_decode_primitive`](../../snekql/storage.py#L1587-L1611) use the Logical Type adapter without `strict=True` for primitive fetches | Constrained values are checked, but representation-changing conversions can be accepted |
| JSON-backed columns | [`_decode_json`](../../snekql/storage.py#L1541-L1571) parses/validates with `validate_json(text)` without an explicit strict flag | Parsing is intentional; acceptance of coercible payload values depends on the inner Pydantic contract |
| Named projections | [`NamedProjection.materialize`](../../snekql/_named_projection.py#L83-L101) uses `model_validate(..., strict=True)` after [`SelectMaterialization`](../../snekql/_query_materialize.py#L145-L171) has decoded slots | A useful final constraint layer, not evidence of strict wire acceptance; user validators can deliberately transform values |
| Raw declared results | [`RawPlan.materialize_row`](../../snekql/_raw.py#L242-L272) packages the row and calls `validate_python(packaged)` | The declared Pydantic contract owns coercion, aliases, defaults, extras and custom validators; no Table Model codec is inferred |
| Native computed expressions/literals | [`ValueExpression.__decode__`](../../snekql/_value_expression.py#L486-L493) and [`_IntegerLiteral`](../../snekql/_literal.py#L38-L49) check exact native types | The library is not uniformly lax; these paths should not be weakened by a common "conversion" abstraction |
| Aggregates/scalars/derived outputs | [`_value_decode.py`](../../snekql/_value_decode.py) retains source policies for extrema, nullability for empty scalars, and separate COUNT/SUM/AVG normalization | Output contracts are not interchangeable with constraints on the rows used in a computation |
| Streaming | [`ChunkStream.__anext__`](../../snekql/runtime.py#L498-L540) materializes a complete fetched batch before returning it | Earlier batches can already be consumed when a later one fails; validation is not whole-stream atomicity |
| Mutation RETURNING | [`materialize_write_returning_rows_for_backend`](../../snekql/_query_materialize.py#L187-L224) shares model/column/named decoding; [`Transaction.execute`](../../snekql/runtime.py#L1335-L1377) materializes after driver execution | A decoding failure does not itself undo a completed write; transaction handling remains intentional |

### Construction is not the fetch policy

[`_validate_logical_value`](../../snekql/storage.py#L1474-L1484) calls
`validate_python(..., strict=True)`, but first handles pending/NULL values and
explicitly converts bool for an integer Logical Type. Tests
`integer_columns_reject_float_in_strict_mode` and
`integer_columns_coerce_bool_to_int` in
[`test_model_declaration.py`](../../tests/test_model_declaration.py) assert those
policies. [#579](https://github.com/crpier/snekql/issues/579) already tracks the
boolean/integer design question; this assessment does not resolve it.

Do not infer the fetched-data policy from constructor behavior, or accidentally
make a read-policy decision change accepted writes.

## Concrete contrasts

### A. Raw validation is deliberately more than a shape check

In [`test_raw_validation.py`](../../tests/runtime/test_raw_validation.py):

- `dataclass_rows_use_pydantic_coercion` declares `amount: int`, selects SQL
  `'42'`, and expects integer 42 across both backends and four consumption methods.
- `model_policy_controls_mapping` expects an alias to be honored, a missing label
  to receive its Python default and an unmodeled result column to be ignored.
- `declared_field_policy_rejects_invalid_values` separately asserts missing,
  forbidden-extra, NULL and strict-boolean failures.

These are explicit current contracts, not bugs established by this assessment.
"The data matches" still needs an agreed interpretation: a successful Pydantic
contract can intentionally adapt data rather than merely attest to its original
shape. Strictness alone also does not select closed versus open rows or prohibit
missing-field defaults.

### B. A strict named model cannot inspect values before column decoding

An ordinary column decoder can turn a numeric string into an integer before the
named result sees it. Existing
[`bulk_returning_keeps_each_executions_validation`](../../tests/runtime/test_projection_decoder.py)
asserts that a logical integer stored as TEXT returns `"7"`/`"8"` unchecked and
7/8 validated. That is a declared storage pairing, not necessarily unwanted repair.

**Source-implied contrast, not a new executed test:** a numeric string returned
for an Integer/int declaration also reaches lax primitive validation. The same
adapter is not itself evidence that the physical declaration's permitted wire
representation was respected. A strict named `int` field sees the integer only
after conversion. A raw strict contract instead sees the packaged driver value,
with no inferred column codec. These routes need not accept the same wire data,
but their differences must be explainable from declared contracts.

### C. Aggregate normalization needs its own acceptance rules

[`_normalize_sum`](../../snekql/_value_decode.py#L28-L39) calls `int(value)` for
Integer storage and `float(value)` for Real storage. COUNT/AVG similarly normalize
through native constructors. MIN/MAX instead retain column validation policies.

**Source-implied counterexample, not a reproduced backend incident:** supplying a
fractional numeric result such as 1.5 to the Integer SUM normalizer produces 1,
rather than rejecting fractional data. A stale/nonconforming schema could be a
source of such a result; that backend scenario has not been executed here.
Lossless conversion of MariaDB's integral Decimal result and fractional truncation
must not be treated as equivalent merely because both produce an `int`.

Other storage/Logical Type combinations also need a matrix: the shared SUM
normalizer leaves storage names other than Integer/Real unchanged, while numeric
eligibility is based on the Logical Type. No cross-backend defect for those pairs
has been certified here.

Existing tests `numeric_aggregate_normalization_is_unchanged` in the
[SQLite](../../tests/query/test_aggregate_validation.py) and
[MariaDB](../../tests/mariadb/test_aggregate_validation.py) files expect normalized
numeric outputs under both validation settings. In
[`test_fixed_aggregate_decoder.py`](../../tests/runtime/test_fixed_aggregate_decoder.py),
COUNT/AVG intentionally ignore source-column constraints. A valid aggregate output
is not evidence that all contributing stored values satisfied those constraints.

## Strengths and constraints to preserve

- **Unexpected NULL already fails a non-null application declaration.** See
  `nullable_column_round_trips_none_for_every_storage_class` in
  [`test_storage_codecs.py`](../../tests/sqlite/test_storage_codecs.py). A model can
  currently reject NULL from a more permissive live schema, but it cannot also
  declare that physical nullability faithfully: the
  [declaration guard](../../snekql/model.py#L833-L872) couples them, and structural
  verification sees their disagreement as drift. This is a schema-contract issue,
  not an absence of runtime NULL checking.
- **Absence and NULL have intentional distinctions.**
  [`SourceRowShape`](../../snekql/_materialization_shape.py) uses presence witnesses
  for matched all-NULL rows. The
  [nullable-table tests](../../tests/runtime/test_nullable_table_presence.py) cover
  physical tables and aliases on both backends. Empty scalar subqueries retain
  NULL independently of a NOT NULL source. Optional single-scalar fetches are
  rejected where None would be ambiguous; see
  [`validate_select_consumption`](../../snekql/_query_plan.py#L148-L159).
- **Known unsound shapes can be refused.** Ordinary positional projection LEFT
  JOIN is rejected in [`query.py`](../../snekql/query.py#L1149-L1158), with an
  existing assertion in
  [`test_row_materialization.py`](../../tests/query/test_row_materialization.py).
  Named projections check nullable bindings. The old "projection nullability
  gap" wording in a decoder comment is not proof that the public rejection is
  absent.
- **Final named constraints survive disabled column validation.** See
  `named_result_constraints_survive_disabled_column_validation` in
  [`test_named_projection.py`](../../tests/runtime/test_named_projection.py).
  Conversely, `validate=False` is not "do nothing": built-in numeric codecs and
  some result policies still run, while public return types widen to object.
- **There are inexpensive verification seams already.** Pure `.compile()` and
  public `complete()` allow SQL inspection and validated Row snapshots without
  database IO. The latter validates logical values, not driver representations.
  Private materializer unit tests help verify the library; consumer fixtures
  made with `complete()` do not by themselves establish real codec/driver behavior.
- **Failure handling is not one uniform contract.** Raw validation has structured
  operation/row-index/redacted-code details in
  [`RawResultValidationError`](../../snekql/errors.py#L254-L278); model failures
  generally identify a column, and named failures report a final-contract error.
  Some builder width checks are assertions rather than controlled validation
  errors. Their behavior under optimized Python was not assessed. Distinguish
  external data mismatch from an internal compiled-layout invariant.
- **Extensions remain trusted code.** Custom Pydantic validators, descriptor
  setters and dialect decoders can transform values. An outer strict call does
  not sandbox them. Existing tests deliberately preserve extension behavior;
  instance checks on named results do not prove arbitrary custom field code.

## Bounded evaluation tasks

These are proposed task oracles, not newly run tests or selected syntax. The
representation choices in T1–T3 require maintainer agreement before changing
behavior. Keep native backend checks separate from pure decoder fault injection.

| Task | Cases and proposed decision evidence |
| --- | --- |
| **T1 — Integer representation** | Contrast Integer/int receiving native 7 versus string `"7"`/float 7.0, and Text/int receiving its declared text encoding. Decide which are valid representations rather than calling every conversion equally acceptable. Include whole-model, scalar, named and RETURNING paths. |
| **T2 — JSON payload** | Distinguish parsing `[7]` from adapting `["7"]` to `list[int]`; retain valid rich JSON codecs. Exercise payload constraints and SQL NULL versus JSON null. Do not infer that global Python strictness preserves JSON decoding behavior. |
| **T3 — Numeric aggregates** | Contrast integral native/Decimal results with fractional results for an integer output; cover empty sets, extrema constraints, native expressions and supported storage/Logical Type pairs on each backend. Record where SQL itself already transformed underlying data. |
| **T4 — NULL, shape and absence** | Reject stored NULL for a non-null read contract; preserve an absent joined row versus a matched all-NULL row. Separately assess faithful nullable-schema metadata, named nullable outputs, extra/missing raw fields and deliberate defaults. Preserve public rejection of unsupported projection forms. |
| **T5 — Intentional failure** | Place invalid data in a later stream batch; identify the failing operation without leaking values and without pretending earlier batches were unseen. For RETURNING, test caught and uncaught failures and the resulting write/transaction state, not automatic validation rollback. |
| **T6 — Practical human/agent verification** | Ask a consumer to explain an existing query, modify its shape and handle a mismatch. Use exact type controls, pure compilation and `complete()` fixtures for the facts they establish, with targeted backend tests for the rest. Compare semantic success, review effort, tool/time/token cost and diagnostic recovery on held-out tasks and varied model runs. |

Existing starting points for T2/T4 are
[`test_optional_json.py`](../../tests/sqlite/test_optional_json.py) and
[`test_select_cardinality.py`](../../tests/runtime/test_select_cardinality.py).
For T5, `late_validation_failure_resets_per_execution` in the raw validation
file explicitly asserts a successful first batch before a later failure;
[`test_multi_field_decoding.py`](../../tests/runtime/test_multi_field_decoding.py)
asserts that a caught named RETURNING failure can leave the write visible.
Neither behavior should disappear under a vague "validation failed" abstraction.

## Next decision, not next knob

First agree on a small acceptance table for T1–T3:

- permitted backend wire representations for declared Column Type/Logical Type
  pairs, including lossless numeric and explicitly curated temporal/JSON codecs;
- which conversions require an intentional application contract instead of
  following automatically from a plain Python annotation;
- what constitutes an unacceptable mismatch, and how strict checking interacts
  with declared validators, defaults, extras and unchecked reads.

Then a separately authorized TDD slice can characterize those cases and assess
implementation alternatives through the shared decoding seam. Preserve the
consumer type contract, backend differences and compatibility evidence. Do not
select a global strict flag, public codec configuration, split-domain notation
or new constructor interface from this source assessment alone.

[Development/staging verification #556](https://github.com/crpier/snekql/issues/556)
is complementary: additional schema/metadata evidence cannot replace the normal
result contract. Migration implementation remains outside this assessment.

## Local validation of this assessment

Ad hoc checks verified 32 relative link targets, bounds for 17 source-line
references, 11 explicitly named test references by AST, and parsing of 13 linked
production files using the project interpreter. These are documentation/source
consistency checks, not execution of the referenced behavior.

`uv run ty check`, `uv run ruff check .`, `uv run ruff format --check .` and diff
whitespace checks passed. No runtime/typing test suites or agent benchmarks were
run, and no new behavioral acceptance is claimed. GitHub Actions are disabled;
validation is local. The script used for the ad hoc checks was temporary, not a
new supported project tool.
