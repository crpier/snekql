# Callable intersections: a native no-pending-boilerplate prototype — #473

2026-10-26. **Promising static prototype, not a production implementation or a
selected final interface.** It uses stock ty 0.0.84, no checker patch, no generated
constructors, no dependency changes, and no per-model typing overlay.

## Result

The eleven core scenarios pass the existing declaration/construction and consumer
controls on both backends, with these shorter server and identity declarations:

```python
value: db.GenCol[bool] = Integer(server_default=False)
clock: db.GenCol[db.UtcDatetime] = Text(server_default=db.CurrentTimestamp)
nullable: db.GenCol[str | None] = Text(server_default="fallback")
null: db.GenCol[str | None] = Text(server_default=None)
id: db.GenCol[int] = Integer(primary_key=True, auto_increment=True)
```

`Integer` / `Text` stand in for proposed backend exports, not installed functions.
Constructor omission is accepted. Pending attributes have the logical type union
PENDING_GENERATION; Rows exclude it. Explicit values and nullable None overrides,
wrong-value rejections, frozen fields, Pending-only construction and INSERT
RETURNING typing remain intact in the tested cases. No Python default parameter
mentions the pending sentinel in those declarations.

Required ordinary/nullable fields still reject omission. A defaultless GenCol
also remains required, while accepting explicit pending input, as in the agreed
review sheet. This does not redefine every GenCol as automatically optional or
certify that generation will succeed without a source.

## Trade-off: the required-input SQL-default contrast is explicit

The prototype retains independent Python and SQL defaults naturally:

```python
value: db.Col[bool] = Integer(default=False, server_default=True)
label: db.Col[str] = Text(
    default_factory=lambda: "client",
    server_default="server",
)
```

No extra flag is needed for those coexistence forms. Python supplies its concrete
value; the SQL fallback serves other writers. That runtime behavior is intended,
not newly executed evidence.

But an SQL default with **required Python input** needs an explicit override:

```python
value: db.Col[bool] = Integer(server_default=False, required=True)
```

`required=True` is a **research-only constructor-required marker**: it says
nothing about SQL NOT NULL. It is not a selected public name. Omitting it in the
plain Col declaration is rejected with `invalid-assignment`, rather than quietly
making the required-input case optional. The same override can keep a GenCol
input required despite a server default if that policy is desired.

Therefore this is NOT the earlier hoped-for rule that the exact same
`Integer(server_default=False)` expression switches constructor requiredness
solely according to Col versus GenCol. Instead, server-only spelling is the
omittable/generated case; the unusual required-input case is explicit.

This **moves the extra marker to the exception**, instead of repeating pending
on every ordinary server-generated field. Whether that is an acceptable public
contract is a maintainer decision, not something the typing experiment selects.
The prototype rejects a simultaneous Python default and required override.

## Mechanism: two callable views, one exported name

`intersection_declarations.py.txt` supplies two views of each constructor:

1. A function registered as a dataclass-transform field specifier. It covers
   required ordinary inputs, explicit Python defaults/factories, independent
   Python/SQL combinations, and the explicit required-input override.
2. A callable Protocol covering server-only and identity declarations. Those
   calls return typed GenCol descriptors and are not handled as registered
   function calls by ty's field-specifier branch. Their ordinary RHS default
   supplies constructor omission, as in the earlier unregistered-helper probes.

Native narrowing combines the views:

```python
Integer = _RequiredInteger
assert isinstance(Integer, _ServerInteger)
```

The metaclass registers `_RequiredInteger`, not the narrowed intersection value.
Calls that match the function side retain requiredness or recognized Python
construction defaults. Calls that match only the protocol side get ordinary
RHS-default behavior. Required no-argument calls do not match the server protocol,
so this avoids the earlier failure that made all ordinary fields optional.

This is a materially different mechanism from adding an implicit default to one
registered function. The [release-pinned hook analysis](native-omission-hooks.md)
remains correct about that single-function route; this prototype combines two
routes under the same public spelling.

## Important limits of this technique

- **This is a checker-sensitive typing trick.** It relies on ty retaining the
  callable intersection and classifying its matching views differently. It is
  not a newly standardized dataclass-transform feature. Support is established
  only for the tested pinned version; future checker changes could affect it.
- A runtime-checkable Protocol checks member presence, not overloaded call
  signatures or semantics. The narrowing supplies a trusted interface contract;
  it does not prove that an implementation fulfills it. Prototype bodies raise,
  and even the assertions are never executed by the tests. Production functions
  would need to implement both views and their lowering correctly.
- There is no Any-erased public callable or constructor in this proof. Exact
  attribute types, declaration mistakes, missing inputs, wrong arguments and
  importing consumers are checked. Ordinary Attr expression/owner placeholders
  and unimplemented overload bodies retain the same research usage of Any as
  prior fixtures; they are not evidence of runtime implementation conformance.
- Some invalid calls produce **two diagnostics on one line**, e.g. an aggregate
  `no-matching-overload` plus a detailed callback argument error. The paired
  helper now allows comma-separated expected rules on a line, preserving exact
  count, order, rules and locations. Diagnostics are noisier than a simple
  function interface, and can expose the private function names.
- The explicit required-input branch retains the earlier accepted SQL-default
  validation gaps: wrong literal/NULL/clock defaults can be accepted despite
  precise input types. These are explicitly tested as accepted gaps, not fixed
  by the callable mechanism. Runtime declaration validation remains necessary.
- The prototype covers Integer/Text and a narrow literal-True primary-key
  identity form, not every constructor, FK, option, codec, identity configuration,
  inheritance pattern or backend behavior. Production metaclass registration
  must preserve requiredness for unchanged storage constructors too.

## Evidence

`tests/research/test_split_intersections.py` has **14 paired checks**, seven on
each backend:

- R1–R11 using the shared independent consumer controls, without pending-default
  arguments on server/identity declarations.
- Factories imported into a separate module where a new user model is declared.
- Required-input override and independent Python/SQL value/factory defaults.
- Wrong Python defaults/factories and server literal/NULL/clock/state declarations.
- Required source-less GenCol, nullable clocks, None-only clock rejection and
  factory arity.
- Imported models with postponed annotations, exact Pending/Row/RETURNING types,
  requiredness, freezing and Pending-only construction.
- Accepted SQL-validation gaps with precise bad-input rejection witnesses and
  contradictory required/default options.

The initial shorter core declarations failed before callable composition, with
missing constructor arguments on both backends. After composition, both baseline
pairs passed; later controls exercised imports and brownfield cases. The helper's
multi-diagnostic extension also had a red/green check against the precise
intersection diagnostics.

```sh
uv run snektest tests/research/test_split_intersections.py
```

**Bottom line:** a stock-ty prototype now removes explicit pending defaults from
common server-generated declarations while retaining the tested lifecycle and
ordinary required-input guarantees. It has an explicit required-input exception
and a nontrivial, checker-sensitive implementation. It is a candidate to evaluate,
not proof that the exact annotation-sensitive design or a production-ready public
interface is finished. No model, factory, INSERT, DDL or database workflow was run.

### Full local validation for this follow-up

`uv run snektest tests/research` passed **224 tests in 31.47 seconds**:
214 paired static checks and 10 historical parser rejection cases. The new hook
observations contribute 14 pairs and this intersection candidate contributes
another 14. Historical generated-route evidence is retained, not revived as a
candidate. `uv run ty check`, `uv run ruff check .`,
`uv run ruff format --check .` and `git diff --check` also passed. No backend
runtime suite or GitHub Actions run was used.
