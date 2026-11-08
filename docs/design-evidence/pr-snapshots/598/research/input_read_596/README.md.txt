# Construction and read inputs: one logical authority, explicit grammars

Research for [#596](https://github.com/crpier/snekql/issues/596), **2026-10-31**.
Baseline: `a1cf31d8dba78f9ddf0a2b687f5c188649c14391`. Follow-up to the separate
[attribute-contract assessment](https://github.com/crpier/snekql/pull/597).
**Research, not adopted behavior or a new public interface.**

## Recommendation

Prefer **one complete logical contract with explicit input entry points**. Use
Pydantic's existing Python/JSON distinction where it fits. Where database input
really differs, compose an explicitly chosen read adapter around that logical
contract rather than weakening application input or duplicating value rules.

This does not require two independently maintained definitions of the value,
new write/read generic parameters, a mandatory result BaseModel, or a new option
on every field. The application-facing declaration remains undecided. Any read
interpretation must be discoverable in the chosen contract/mapping; automatically
attaching hidden converters by physical column type would recreate the competing
semantic authority we are trying to remove. In particular, these probes do not
justify converting SQL integer 1 for a plain `StrictBool` field merely because
its physical column is Boolean: that acceptance must belong to its explicitly
chosen read contract.

Do **not** choose a framework-wide `context = SQL read` flag as the default
solution: it works locally but also affects reused contracts nested inside JSON.
Application-defined validation context remains legitimate; it is not forbidden.

## Scope and evidence

Executed **57 focused cases** through the confirmed public Pydantic `TypeAdapter`
seam. They use synthetic inputs and the existing public
`sqlite.UtcDatetime`/`sqlite.LocalDatetime` logical values. Actual nominal value
construction, canonical wire parsing and Pydantic schemas execute; application
Table Models, queries, runtimes, connections and native backends do not.

Files:

- [Research-only read policies](../../tests/research/input_contracts.py).
- [Executable comparison and controls](../../tests/research/test_input_read_contracts.py).

Application-input calls use `strict=True`, matching current snekql construction.
Read calls use `strict=None` or `strict=True`, independently of construction.
No new constructor parsing mode is proposed. No-parsing whole-row typing,
aggregates, migrations, performance and production integration are deferred.

Environment: Python 3.15.0, Pydantic 2.14.0, pydantic-core 2.50.0, ty 0.0.84 and
snektest 0.16.0. The 120-case assessment in PR #597 is separate and not included
in this branch or count.

## The alternatives

| Choice | Benefit | Cost / demonstrated limit |
| --- | --- | --- |
| One shared annotation accepting application and SQL inputs | Small interface; one adapter | Its before-validator also runs during strict application input; accepting SQL integer 1 broadens construction |
| One logical contract, explicit read composition | Reuses constraints and custom validators; keeps application input unchanged | Must select/retain read interpretation metadata and grammar; potentially multiple cached adapters |
| One context-sensitive contract/adapter | Per-call phase selection without mutating the adapter | Caller discipline, context composition and nested propagation become part of the interface |

These are choices about **input acceptance**, not different successful Logical
Types. A shared annotation is fine if its broader application acceptance is
actually wanted. It is not fine merely because that saves an internal adapter.
No adapter-count performance conclusion is established. Merely moving today's
converters into before-validators does not remove their work or demonstrate
extra Depth. The useful change would be explicit contract ownership, reuse of
logical rules and one consistent execution policy—not a renamed hidden codec.

## Boolean: a real input-domain difference

The research compares these Pydantic configurations, not proposed snekql syntax:

```python
application = TypeAdapter(StrictBool)
read = TypeAdapter(Annotated[StrictBool, BeforeValidator(sql_bool01)])
```

`sql_bool01` maps exact Python integers 0/1 to bool; other values reach the
unchanged logical contract. Read validation accepts 1 as Boolean true under both
operation modes. Application validation still rejects integer 1 under strict
construction. Read controls reject 2, text `"1"`, `"yes"`, float `1.0` and NULL.

Using the entire read annotation for application input accepts integer 1 there,
even with `strict=True`. That is executed evidence, not a hypothetical concern:
strict built-ins do not disable an explicitly declared before-validator.

The representation rule is additional policy, but the logical Boolean contract
has not been rewritten. This earns a real seam: the accepted application and SQL
inputs vary while the required successful value remains the same.

## JSON: one complete payload contract is sufficient

The payload fixture combines `list[StrictInt]`, minimum/maximum length and an
application custom validator excluding 13. The **same adapter** validates Python
`[7]` for application input and JSON `[7]` for a read:

```python
adapter = TypeAdapter(Payload)
application_value = adapter.validate_python([7], strict=True)
read_value = adapter.validate_json("[7]", strict=operation_strict)
```

Both routes enforce the complete element, container and custom constraints.
Empty/overlong lists, 13, textual integers and booleans are rejected. A deliberate
non-idempotent validator appending 99 produces `[7, 99]` on either route, not
`[7, 99, 99]`: select the right grammar rather than parse then revalidate the
completed value.

Wrong-grammar controls also matter: Python validation of plain `Payload` rejects
JSON text, while `TypeAdapter(Json[Payload]).validate_python([7])` rejects an
already-logical Python list. No second payload policy or SQL-element decoder is
needed. This is an extension of the existing dispatch, not a reason to erase it.
SQL NULL versus JSON null and marker placement remain deliberate separate work;
this slice uses non-null payloads and does not settle those semantics.

## Temporal values: reuse meaning and canonical parsing, do not infer it

The existing public schemas already distinguish strict nominal Python values
from canonical wire text. See accepted
[ADR 0022](../../docs/adr/0022-explicit-temporal-meanings.md), the
[temporal guide](../../docs/temporal-contracts.md), and
[`_temporal_schema`](../../snekql/_temporal.py#L17-L39). These are the actual
schemas exercised, not copied nominal stand-ins.

The logical fixture is `UtcDatetime` with one custom constraint requiring year
2026 or later. Application validation requires a nominal `UtcDatetime`; it still
rejects bare datetimes and wire strings. Explicit read compositions accept:

| Chosen read interpretation | Synthetic input | Successful value |
| --- | --- | --- |
| Canonical UTC text | `2026-10-31T09:30:00.123456Z` | UTC instant, all six fractional digits retained |
| Native fields explicitly interpreted as UTC | Naive `datetime` with those fields | The corresponding UTC instant |
| Native fields explicitly interpreted as civil | The same naive `datetime` | A `LocalDatetime`, no invented timezone |

Text parsing delegates to `TypeAdapter(UtcDatetime)`'s declared canonical wire
policy, **not** a reimplementation of its timestamp grammar or a forced
`strict=False` on the full field contract. The outer read adapter applies the
complete logical annotation with the selected operation strictness. Explicit
conversion remains allowed under strict mode, as agreed for custom validators.

The native UTC adapter explicitly tags timezone-free fields as UTC; the civil
adapter preserves them as civil. Neither derives that meaning from a bare
DATETIME primitive or the host timezone. The probes reject aware/fold-bearing
native inputs instead of silently dropping their metadata. This is evidence for
the selected synthetic policies, not confirmation of native-driver behavior.

The same year constraint rejects old application values, old wire text and old
native fields. A separate non-idempotent logical after-validator advances one
second on both application and read routes, not twice: the read wire parser
reuses the public nominal type's parser, not the complete business annotation as
an intermediate validation pass. These controls exercise preservation of the
specific constraints/after-validators shown, not a claim that every arbitrary
before/plain/wrap validator commutes with a representation parser. The chosen
composition order is part of the contract; callbacks remain trusted policy.

**Important limit:** an added before-validator does not automatically narrow all
of the base type's declared acceptance. In the observed native-field composition,
canonical wire text still passes in declared mode because the underlying
`UtcDatetime` allows it; it fails under strict mode because the native converter
does not convert text. If exact storage-carrier whitelisting is required, it
must be declared too, not assumed from the callback's name. These small adapters
are evidence about composition, not complete storage specifications.

Canonical controls reject old three-digit precision, alternate UTC spellings,
NULL and unrelated raw datetime inputs on the text route. Serialization,
native-year ranges, lower precision, zoned identity and backend round trips are
not newly proved here.

## Context: possible, but not a free phase distinction

The context prototype uses one identity token and one context-sensitive Boolean
before-validator. It rejects integer 1 without the token, accepts it with the
token in both read modes, then rejects it again without the token using the same
adapter. That demonstrates execution-local selection without adapter mutation;
it is not a concurrency or Execution Plan test.

But context is propagated into nested validation. Reusing that Boolean contract
inside a JSON list and supplying the SQL-read token makes JSON `[1]` validate as
`[True]`. Without the token it rejects the integer, including in declared mode.
The read operation has accidentally selected SQL-cell interpretation inside a
JSON payload that was intended to retain strict Boolean elements.

A read-only outer adapter around the unchanged logical `StrictBool` does not
change `list[StrictBool]`'s JSON acceptance. More sophisticated scoped context
could avoid this example, but then path/grammar scope, nested adapters and
application-owned context all become explicit interface obligations. A global
phase bit is not a substitute for that design. The experiment does not prove
that every possible context design is unsound.

## Relation to current snekql

These are **source inspections, not executed Table Model behavior**:

- [Construction](../../snekql/model.py#L948-L990) calls column validation before
  storage, and [`_validate_logical_value`](../../snekql/storage.py#L1474-L1484)
  uses `strict=True`. Its NULL/pending/int-Boolean handling remains separate
  from Pydantic; this research does not silently adopt or remove those rules.
- [Logical adapter resolution](../../snekql/storage.py#L1486-L1502) strips JSON
  transport markers; [JSON reads](../../snekql/storage.py#L1541-L1571) already
  use `validate_json`. Preserve the useful grammar distinction.
- [Current native timestamp decoding](../../snekql/storage.py#L1696-L1701)
  combines driver fields with declared UTC/civil meaning. A replacement needs
  that deliberate interpretation, not merely `TypeAdapter(datetime)`.
- [Row Materialization](../../snekql/_model_materialization.py#L72-L99) calls
  setters; default [`Attr.__set__`](../../snekql/storage.py#L1332-L1340) stores
  values, while custom setters may have additional behavior. Do not add a
  second application-validation pass merely because construction uses one.

There is a plausible implementation direction: an immutable, execution-local
read plan retains the full logical annotation, selected input grammar and any
explicit representation policy. It delegates interpretation to the selected
Pydantic contract and uses the same materialization paths for operation policy.
No parsing selects none of these semantic validators. This report implements
none of that plan, nor any public declaration for choosing it.

## Decision supported and remaining work

The evidence supports **sharing logical authority, not necessarily sharing the
entire input contract or exactly one adapter instance**. Prefer built-in grammar
entry points first, explicit read composition when needed, and no global read
context as an assumed shortcut. Whole-operation strictness remains independent
of the construction/read distinction; no per-attribute strictness override has
been introduced.

The implementation/interface still must answer:

1. How an attribute retains its complete logical metadata plus any chosen
   SQL-input interpretation, without parallel business validators or hidden
   physical-type-driven interpretation.
2. Whether each chosen contract deliberately includes base-type lax inputs or
   requires exact storage-carrier acceptance, especially around NULL placement.
3. How read policy reaches projections, named results and shared RETURNING
   without accidental extra logical validation or changed failure semantics.

Next compare those obligations with no-parsing whole-row shape/typing, then
scope native Transaction tests before production integration. Do not expand this
into a generic parser framework. No native compatibility, lower implementation
complexity, agent-task or performance benefit has been measured.

## Validation

```sh
uv run snektest tests/research/test_input_read_contracts.py
uv run ty check
uv run ruff check .
uv run ruff format --check .
git diff --check
```

The five research-only callbacks used vertical red/green checks at TypeAdapter:
Boolean, UTC text, UTC native fields, civil native fields and contextual Boolean.
Identity callbacks initially failed the intended read cases, then each minimal
policy made its slice pass. The text case already passed declared mode but
failed strict mode before its explicit parser was introduced. Remaining probes
observe the alternatives and add negative/metadata/grammar controls, not changes
to Pydantic. Ruff import sorting/formatting was mechanical.

Focused result: **57 passed in 0.04s**. Project typing, lint, format and whitespace
checks passed; Ruff checked formatting for 815 files. Report checks covered 12
relative targets, eight source-line bounds, six linked Python files, 16 test
functions and nine named controls by text/AST, without importing linked
production/test modules in that check. The actual focused tests do import the
public temporal types as stated.
No full suite, SQL/backend test, benchmark, new result-typing consumer, dependency
change, production change, issue closure or merge is included.
