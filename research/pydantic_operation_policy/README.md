# Per-operation Pydantic validation and driver-value reads

Research for [#593](https://github.com/crpier/snekql/issues/593), dated
**2026-10-27**. Continues the result-contract assessment in
[draft #592](https://github.com/crpier/snekql/pull/592) and the purpose discussion in
[draft #589](https://github.com/crpier/snekql/pull/589). **Not adopted behavior or
usage instructions.** No public spelling or compatibility policy is selected.
Aggregates are deliberately deferred.

## Question and scope

The maintainer proposes individual attribute contracts using Pydantic types and
`Annotated` validators/serializers, rather than a second snekql-owned semantic
decoding policy. For example, can one `age` attribute accept ordinary Pydantic
integer conversions in one function but require strict integer input in another?
For unchecked reads, driver values now look preferable to best-effort decoding.

This report inspects source, documentation and existing tests; it does not execute
models, validators, queries or tests. The snekql baseline is
`3ed75324bbb12b189470f296e55faddf63d72b5b`. Installed distribution metadata reports
**Pydantic 2.14.0 / pydantic-core 2.50.0**. Upstream references below are pinned to
Pydantic v2.14.0's commit `fcdefa7198c4fc94a22eecf1a5b7926e20b9fc8a`.
Installed `pydantic/type_adapter.py` and `pydantic/types.py` match the corresponding
pinned upstream files byte for byte; the compiled core's provenance is not
independently established. Existing upstream assertions are evidence of intended
behavior, not newly run tests on this machine.

## Finding: no need to swap the declared type

Pydantic already exposes a per-call `strict: bool | None` on the same adapter.
The following is **illustrative Pydantic code, not an executed prototype or a
proposed snekql setting**:

```python
from pydantic import TypeAdapter

age = TypeAdapter(int)
age.validate_python("42", strict=False)  # returns int 42
age.validate_python("42", strict=True)  # raises ValidationError
age.validate_python(42, strict=True)  # returns int 42
```

`StrictInt` is `Annotated[int, Strict()]`, not a different successful Python
value type. There is no reason to mutate the Table Model's annotations, make a
second table declaration or rebuild an adapter just to change this built-in
acceptance policy. Both validated modes still produce an integer; they differ
in which inputs may produce it. Native static typing of a future snekql setting
is not demonstrated by this source assessment.

### Three validation settings, not two

For Python input `"42"`, without additional adapter configuration, the built-in
integer behavior is:

| Declared contract | `strict=None` / omitted | `strict=True` | `strict=False` |
| --- | --- | --- | --- |
| `int` | integer 42 | reject | integer 42 |
| `StrictInt` | reject | reject | integer 42 |
| `Annotated[int, Strict(False)]` | integer 42 | reject | integer 42 |

The last column is significant: **an explicit call override can relax even
`StrictInt`**. Conversely, `strict=True` can override a field explicitly marked
`Strict(False)`. `None` means preserve the declaration/configuration, not force
lax behavior and not bypass validation.

Evidence:

- [TypeAdapter](https://github.com/pydantic/pydantic/blob/fcdefa7198c4fc94a22eecf1a5b7926e20b9fc8a/pydantic/type_adapter.py)
  forwards the call argument to its existing compiled validator.
- [Strict metadata and aliases](https://github.com/pydantic/pydantic/blob/fcdefa7198c4fc94a22eecf1a5b7926e20b9fc8a/pydantic/types.py)
  define `StrictInt = Annotated[int, Strict()]`.
- [Integer tests](https://github.com/pydantic/pydantic/blob/fcdefa7198c4fc94a22eecf1a5b7926e20b9fc8a/tests/types/test_int.py),
  `test_int_strict_argument`, cover this cross-product for Python and JSON input;
  `test_strict_int` also rejects booleans and fractional floats by default.
- [Integer validators](https://github.com/pydantic/pydantic/blob/fcdefa7198c4fc94a22eecf1a5b7926e20b9fc8a/pydantic-core/src/validators/int.rs)
  use `state.strict_or(self.strict)`; [validation state](https://github.com/pydantic/pydantic/blob/fcdefa7198c4fc94a22eecf1a5b7926e20b9fc8a/pydantic-core/src/validators/validation_state.rs)
  implements that as the call override or the schema default.
- [Adapter tests](https://github.com/pydantic/pydantic/blob/fcdefa7198c4fc94a22eecf1a5b7926e20b9fc8a/tests/test_type_adapter.py),
  `test_validate_python_strict`, cover overriding strict configuration. The
  adjacent `test_validate_json_strict` is marked **xfail**, so its assertions
  are not cited as passing evidence; the integer matrix above is separate.

A future snekql interface must decide whether to expose this native precedence
or impose a different rule such as "operations may tighten but never relax a
strict declaration." The latter would be additional library policy. Neither
choice is selected here.

## What the override does not mean

### Lax validation still validates

`strict=False` does not mean `Any`, driver values or ignored constraints. A
non-numeric string still cannot satisfy `int`. The constrained integer validator
in the source above still applies range/multiple checks after integer parsing;
an age outside a declared range is not made valid just by allowing numeric text.

This makes ordinary validation a plausible permissive mode **without a second
best-effort decoder**. A complete bypass instead must avoid validating through
the logical contract.
There is no `TypeAdapter` validation argument that means "do not validate and
return its input." Pydantic does provide
[`SkipValidation[T]`](https://github.com/pydantic/pydantic/blob/fcdefa7198c4fc94a22eecf1a5b7926e20b9fc8a/pydantic/functional_validators.py):
its schema accepts any value while its static annotation remains `T`. That is a
trust-the-caller annotation, not evidence that unknown driver data has type `T`.
Calling no adapter at all is sufficient for a raw-cell path. Constructing an
unchecked model is not the same operation as returning driver cells without
interpreting them.

### Strictness is not a universal conversion veto

[Validator documentation](https://github.com/pydantic/pydantic/blob/fcdefa7198c4fc94a22eecf1a5b7926e20b9fc8a/docs/concepts/validators.md)
places `BeforeValidator` before built-in validation. An explicit callback may
convert text to an integer before a strict integer validator sees it. Plain
validators can replace built-in validation altogether. Custom schemas can also
have behavior not governed by the built-in strict switch.

Thus strictness selects Pydantic's built-in acceptance rules; it does not disable
application callbacks, prove their output annotations, or prohibit the explicit
storage conversions those callbacks declare. This is compatible with the
maintainer's proposal, but not with a claim that strict mode runs no conversion.
If callbacks need application policy, `context=` is a separate mechanism, not
an automatic replacement of arbitrary custom behavior by strict equivalents.
The public
[`ValidationInfo`](https://github.com/pydantic/pydantic/blob/fcdefa7198c4fc94a22eecf1a5b7926e20b9fc8a/pydantic-core/python/pydantic_core/core_schema.py)
exposes `mode` as Python/JSON, not strict/lax; stored configuration should not be
mistaken for the effective per-call override. Passing application policy to
custom callbacks would require deliberate context propagation.

### JSON and Python input are different contracts

[Strict-mode documentation](https://github.com/pydantic/pydantic/blob/fcdefa7198c4fc94a22eecf1a5b7926e20b9fc8a/docs/concepts/strict_mode.md)
shows strict `date` validation rejecting a Python string but accepting a JSON
string through `validate_json`. This is intentional: JSON cannot carry a Python
`date` instance. Strict integer validation still rejects a numeric JSON string.

An actual JSON attribute should use its declared JSON contract. Converting every
ordinary SQL cell into JSON to obtain JSON-mode acceptance would change the
contract, not merely optimize the implementation. That shortcut is not proposed.

### Operation-wide is not attribute-selective

Applying `strict=True` to every attribute in a fetched model also affects UUIDs,
dates and other fields, not just `age`. Their explicit storage types/validators
may accept the driver representation, or ordinary strict Python validation may
reject it. A single call flag does not mean "tighten only the age field."

Switching a scalar age query per operation is straightforward at the Pydantic
seam. Selectively changing one attribute of a whole-model result requires a
further choice: separate result contracts, attribute-specific overrides, or
context-aware application validators. None is demonstrated or selected here.
A function's identity alone cannot tell validation which behavior was intended.

## Driver-value bypass is a separate path

Here "driver values" means the Python values returned by the configured driver
**after SQL evaluation and any driver conversion**, not raw database bytes.
The library may package them in tuples/mappings, but should not run logical
validators, JSON parsing, native codecs, expression decode hooks, named-result
validators or model setters that could reinterpret them.

The result cannot retain the normal logical Row Model promise: text in UUID
storage is not necessarily a `UUID`, and JSON text is not its payload type.
Existing raw SQL already offers `dict[str, object]` or `tuple[object, ...]` without
a Pydantic contract; see [raw SQL](../../docs/raw-sql.md). Raw query results still
have width/metadata, cardinality, transaction and resource-lifecycle checks.

**A true bypass is not implemented by merely skipping Pydantic in today's
materializer.** Existing snekql behavior differs:

| Current location | Why a bypass/strictness redesign must consider it |
| --- | --- |
| [`Attr.decode`](../../snekql/storage.py#L1347-L1393) | `validate=False` still routes JSON and native Boolean/DateTime through conversion; ordinary primitives return early. |
| [`_validate_logical_value`](../../snekql/storage.py#L1474-L1484) | Forces `strict=True` after NULL/pending and boolean-to-integer handling; the adapter cannot control original representations already changed. |
| [`_decode_primitive`](../../snekql/storage.py#L1587-L1611) | Uses annotation/default strictness, but normalizes BLOB buffers first and checks canonical date text afterward. Its "lax" description does not imply overriding explicit strict annotations. |
| [`_decode_json`](../../snekql/storage.py#L1541-L1571) | Disabled validation still calls `json.loads`; validated reads use `validate_json` on the payload contract. |
| [`NamedProjection.materialize`](../../snekql/_named_projection.py#L83-L101) | Always validates the final model strictly, after earlier conversions, even when column validation is disabled. |
| [`resolve_projection_decoder`](../../snekql/_value_decode.py#L152-L202) | Resolves execution-local column decoding; expression paths have additional hooks. Bypassing only column adapters is insufficient. |
| [`decode_model_values`](../../snekql/_model_materialization.py#L72-L99) | Builds a Row Model through attribute setters; a raw tuple/mapping should not silently exercise those logical-model hooks. |
| [`RawPlan.materialize_row`](../../snekql/_raw.py#L242-L272) | Already packages driver cells without an adapter when the statement has no contract. |
| [`lower_raw`](../../snekql/_raw.py#L275-L298) | Currently rejects operation `validate=False`; raw statement construction owns whether there is a contract. A per-operation bypass would be new behavior here too. |

[`fetch_one`](../../snekql/runtime.py#L1130-L1206) and
[`execute`](../../snekql/runtime.py#L1300-L1377) already distinguish validated
logical results from unchecked `object` results in overloads. Preserve truthful
widening or choose explicit raw containers; do not advertise the normal logical
Row type for unvalidated driver cells. Whether query-builder bypass returns a
flat physical tuple, a mapping, or grouped source values remains open, including
joined and named queries. No raw Table Model state is introduced here.

Current NULL shortcuts also need deliberate treatment: physical SQL nullability
must not silently supply a successful `None` contrary to the chosen Pydantic
contract. Query-induced NULL and absent joined rows remain structural/result-domain
questions, not just strictness settings. This does not implement the separate
nullability research or adopt a schema policy.

## Locality and trade-offs

The existing per-column adapter cache is useful: keep an immutable declared
contract and pass operation policy to validation, rather than changing a model,
shared adapter configuration or process-wide setting. Current select
[Materialization](../../snekql/_query_materialize.py#L83-L143) already captures
validation policy per execution. Extending that concept is plausible, but no
concurrency, streaming or RETURNING behavior has been newly verified here.

Benefits of investigating this direction:

- familiar types/annotations own acceptance and explicit conversions;
- strict and permissive validated operations can retain the same successful type;
- raw reads have one honest promise rather than partial logical decoding;
- one declaration/adapter can serve different calls without duplicated table
  metadata or a second best-effort interpretation of custom types.

Costs that do not disappear:

- useful storage representations need suitable Pydantic types/validators;
- existing storage checks, such as canonical date text, need explicit owners;
  choosing Pydantic does not establish that those checks are unnecessary;
- global strict overrides can affect fields intentionally declared permissive;
- custom contracts remain trusted application code;
- raw output shape and compatibility for the current hybrid mode need decisions;
- serialization, backend wire requirements and canonical SQL comparison behavior
  still require design on writes; removing read validation does not remove them;
- error redaction, structured mismatch handling and execution-local failure
  semantics must survive integration;
- performance requires workload evidence, not an assumption that bypass is fast
  enough to justify a separate interpretation path.

## Next evidence, before implementation

The smallest useful next behavioral work would cross these **proposed seams,
requiring maintainer confirmation before tests**:

1. **Pydantic public `TypeAdapter` validation**: reproduce the integer precedence
   matrix; retain range constraints; contrast an explicit before-validator and
   JSON/Python input. Catches contract semantics, not snekql integration or
   driver representations. The upstream matrix can supply independent expected
   outcomes rather than assertions derived from a new adapter implementation.
2. **Public Transaction operations with native backends**: ordinary/strict reads
   of one attribute, then a mixed whole-model result and genuine driver-value
   bypass. Check the same query reused with different policies, stream policy
   lifetime and shared RETURNING behavior. Catches integration and real driver
   forms, not every storage/logical pair or operational failure.
3. **Consumer static result types**: validated strict/ordinary results keep their
   logical type; raw or dynamically bypassed results cannot leak that promise.
   Catches advertised typing, not runtime conformance of custom validators.

Use separately scoped TDD for implementation and appropriate native validation;
this report adds no tests or adapters. Aggregates remain for later investigation.
The immediate design decisions are override precedence, whole-operation versus
attribute-selective scope, and raw output shape—not a new public knob yet.

## Local validation and limits

Local checks passed: 13 relative link targets, 12 source-line bounds, parsing of
seven linked production files, four upstream test-name references (including the
JSON adapter test's xfail marker), and upstream source URLs matched against GitHub
metadata. The ad hoc checker uses AST/text inspection, not imports of project or
test modules. Source-line bounds do not establish behavioral correctness.

`uv run ty check`, `uv run ruff check .`, `uv run ruff format --check .`, and diff
whitespace checks passed. Ruff's first format check found comment-spacing changes
in the illustrative Python block; those were applied before rechecking. No
`snektest` suite, backend operation, model/validator execution or benchmark was
run. Static/style checks are not runtime evidence. No production, dependency,
public-interface or migration changes are included; no issue closure or merge
is requested.
