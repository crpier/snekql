# Model definitions: deeper research

Research for [issue 396](https://github.com/crpier/snekql/issues/396). This branch
is independent of the first-pass experiments. Production code is unchanged.

**The earlier conclusion was premature. There are useful handwritten model
alternatives without code generation, plugins, or selector lambdas.** Two now
have executable prototypes using actual SQLite INSERT RETURNING.

This is model-definition research, not a proposed library implementation. The
runtime deliberately leaves out most SQL compilation and backend behavior.

## 1. Separate input/read classes, shared descriptor fields

```python
class NewAccount(Record):
    id: Field[int | Omitted] = field(default=OMIT)
    name: Field[str] = field()
    nickname: Field[str | None] = field(default=None)


class Account(NewAccount):
    id: Field[int] = required()
    create = insert_using(NewAccount)
```

```python
command = Account.create(name="Ada")  # Insert[Account]
command = Account.create(name="Ada", id=42)  # Explicit override remains valid
pending = NewAccount(name="Ada")  # pending.id: int | Omitted
read = Account(name="Ada", id=42)  # read.id: int
column = Account.name  # Column[Account, str], inherited without losing owner
```

Missing required inputs, wrong values, unknown keywords, wrong explicit IDs,
and incomplete read-row construction are rejected by ty. Optional fields stay
optional. A second generated field works the same way as the ID; generated
nullable fields retain `None` after removing `Omitted`.

Both classes are immutable. That matters: refining `int | Omitted` to `int` is
safe only if code accepting the input base cannot put an omitted value back into
a fetched object.

### What changed from the first pass

I previously coupled separate input/read classes with ordinary dataclasses and
selector lambdas. That coupling was unnecessary. Descriptor fields can be
inherited, with `__get__` binding the concrete accessing class as their owner.
You keep `Account.name`, not `table.column(lambda row: row.name)`.

`insert_using(NewAccount)` is another descriptor. It captures the input
constructor's `ParamSpec`; class access supplies the read-row owner. Its bound
call returns `Insert[Account]` without a fetched-type forward reference or
lifecycle parameter. The input type does not need to be repeated as a generic
base argument on `Account`.

`required()` reuses the inherited generated-field fact while replacing its
constructor default and logical type. There is no repeated nongenerated field
list. SQL storage metadata is not implemented here; preserving that metadata
would be part of a production version of the refinement operation.

### Costs and limits

- Two class names instead of one, and one repeated annotation per generated
  field. No repeated ordinary fields and no lifecycle generic machinery.
- An inherited create descriptor keeps its original input signature. Adding a
  required field to a read subclass does not automatically add an input argument.
  The executable prototype catches this before SQL. The explicit repair is a
  corresponding input subclass and a rebound `insert_using(...)` descriptor.
- ty accepts an unrelated inherited-field override such as `int | Omitted` to
  `str`. The prototype rejects this at declaration time. Its `required()` rule
  permits exactly removing `Omitted`, not arbitrary changes to the domain.
- Input contracts expose descriptors to support inheritance. A production query
  builder still needs rules distinguishing input contracts from physical tables.
- Backend identity, schema registration, relationships, codecs, and migrations
  have not been implemented in this runtime.

**Verdict:** a credible alternative when explicit pending objects and strict
read-row construction matter. This deserves comparison with the current model
interface, rather than dismissal as extra dataclass boilerplate.

## 2. One class, deferred insert construction

```python
class Account(Model):
    id: Field[int] = field(default=OMIT)
    name: Field[str] = field()
    nickname: Field[str | None] = field(default=None)
```

```python
command = Account.create(name="Ada")  # Insert[Account], not an Account
command = Account.create(name="Ada", id=42)
row = await command.execute(connection, table="records")
# row: Account; row.id: int
```

This removes all lifecycle parameters, fetched-type witnesses, and generated
value unions from the declaration. `Account.id` remains a typed column. Required
fields, keyword names, explicit overrides, nullable values, and client defaults
are checked. Caller probes also reject mismatched literal/default-factory types.

The important implementation detail is that `.create(...)` **does not call the
row constructor**. It validates input values and builds an insert command. The
row constructor runs after the database supplies complete returned values.

The inherited classmethod's typing mechanism is:

```python
@classmethod
def create[**Parameters, Row: Record](
    cls: Callable[Parameters, Row],
    *args: Parameters.args,
    **kwargs: Parameters.kwargs,
) -> Insert[Row]: ...
```

A dataclass-transform-generated constructor provides both the exact named
parameter list and the returned model type. Unlike overriding a metaclass call,
borrowing that signature does not discard required-argument checks.

### The actual tradeoff

The constructor signature has to describe omittable generated values for
`.create()` to borrow it. Consequently:

```python
Account(name="Ada")  # Accepted by ty; raises ModelError at runtime
```

The prototype does not create an object that secretly contains a marker behind
an `int` annotation. It rejects incomplete direct construction. Complete direct
construction, such as `Account(name="Ada", id=42)`, works.

There is also no typed pending `Account` to inspect. Callers hold an insert
command, or keep their application input data separately. This is a changed
construction interface, not a free preservation of every current guarantee.

The plain `Field[int]` version requires omitting an ID keyword rather than
explicitly passing `OMIT`. A tested variation retains that input operation:

```python
id: Generated[int] = generated(default=OMIT)
```

Its constructor setter accepts `int | Omitted`, while instance reads and SQL
columns remain `int`. This variation also runs against SQLite. It adds a
separate generated-field annotation, but still needs no lifecycle generic.

**Verdict:** the smallest useful declaration found in this pass. Worth considering
if `Account.create(...)` can be the normal write interface and runtime rejection
of incomplete direct construction is an acceptable cost. The two-class design
avoids that particular cost.

## A smaller improvement to the existing model interface

The existing runtime already makes model instances immutable, but ty accepts
`account.name = "Grace"`. An identity decorator carrying
`dataclass_transform(frozen_default=True, ...)` makes that assignment fail
statically while preserving the tested constructor, pending-ID, and column-update
checks on real snekql models. SQL assignments such as `Account.name.to("Grace")`
remain valid.

This is an independent improvement if the current model syntax stays. The probe
uses a decorator to avoid editing production; adopting the flag in the library's
own transform declarations would still need production regression tests.

## What was tried, including failed repairs

| Approach | Observed result |
| --- | --- |
| Shared input/read descriptor classes | Works; no selector lambdas or duplicated ordinary fields. |
| Generic `Read[Input]` base with `Self` return | Works in an initial probe; the constructor descriptor removes the explicit input generic from the read class. |
| Constructor descriptor capturing input `ParamSpec` | Works; preserves named input checks and infers the accessing read subclass. |
| One model with borrowed constructor parameters | Works; missing generated values must be handled as command inputs, not incomplete row objects. |
| `init=False` generated columns | Constructor omits the field entirely. Typed `.with_(Account.id.to(42))` repairs explicit override support, but keyword overrides and direct construction are less convenient. |
| `__new__` returning `Write[Self]` | Exact return type works; missing, mistyped, and unknown constructor keywords all go unchecked with a broad signature. |
| Metaclass `__call__` returning a command | Same argument-checking loss. |
| Repair `__new__` by capturing its own constructor signature | In the tested call, inference produces `Write[Write[Never]]` and rejects the intended constructor. |
| Repair metaclass `__call__` with recursive constructor capture | ty reaches a cycle panic or exceeds the five-second guard. This is a checker failure, not a successful rejection. |
| Class decorator replacing the class with a typed factory | Keeps input checks, but the decorated name is no longer usable as the row type or column namespace. Keeping a separate undecorated row class works but adds a binding. |
| Parameterize only the missing generated value | Pending/fetched attributes and class columns infer precisely with explicit table binding. An unconstrained missing-type variable admits wrong ID types through inference. |
| Bound that variable to `Omitted`, use `Never` for read rows | Repairs the wrong-value inference hole. Still needs explicit input/read specialization binding and does not prevent incomplete read construction by itself. |
| Unannotated typed descriptors | Class column types work, but dataclass-transform does not synthesize the corresponding keyword constructor fields. |
| Method/decorator-declared fields | Same missing constructor-field synthesis. |
| Plain scalar `Annotated` fields | Ordinary data construction works; class attributes are scalars to ty, not typed SQL columns. |
| Read-only TypedDict input/read refinement | Optional input keys can become required read keys. Native `Account.name` column access is absent. |
| Client-generated IDs via a default factory | No pending generated value is needed. Useful when the application can supply the value, not a replacement for arbitrary server defaults. |
| Reparameterize `Self`, higher-kinded model variable, generic TypedDict `Unpack` | The specific tested forms are rejected. They do not provide an automatic generic pending-to-fetched mapping under this checker. |

The bounded generated-value variation, for comparison:

```python
class Account[Missing: Omitted = Never](ValueModel):
    id: GeneratedValue[int, Missing] = server(default=OMIT)
    name: Field[str] = field()


accounts = Table(Account[Omitted], Account[Never])
```

It has a simpler value-union mechanism than lifecycle-dependent descriptor
returns, but moves the input/read association into table binding and exposes a
bottom type. I would not choose it over the two leading designs without a
specific reason to prefer one generic schema over two nominal classes.

### More subtle observations

- Inheritance does not inherently lose column ownership. Both the static and
  executable prototypes preserve the actual read subclass in `Account.name`.
- The factory's returned owner can update to a subclass while its input signature
  remains fixed. Testing only the returned type would have missed this.
- Preserving a foreign-key target on the class-access descriptor checks later
  `.references(...)` calls. It does **not** make ty reject a mismatched target in
  a dataclass-transform field declaration. Ordinary descriptor assignment does
  reject the same mismatch. The existing snekql declaration has the same accepted
  counterexample. Runtime relationship validation remains necessary.
- The runtime initially discarded nested `Annotated` metadata during type-hint
  resolution. A failing logical-constraint test caught it; using
  `include_extras=True` preserves Pydantic validation before SQL.

## Existing-model controls

The comparison includes actual current snekql models, not only invented contracts.
Normal missing-input and mismatched-default checks still work.

An unusual existing escape hatch is also recorded:

```python
row = ExistingAccount[database.Fetched](name="Ada")
# ty: row.id is int
# runtime: row.id is PENDING_GENERATION
```

A runtime test reproduces that discrepancy. It does not make the new single-class
tradeoff equivalent: its incomplete direct constructor is much easier to call by
accident. Nor does it invalidate the current normal pending/fetched usage.

The static inherited-witness control observes a base read type, but current
snekql explicitly rejects concrete-model inheritance at runtime. It is not being
presented as a bug in supported inheritance behavior. The prototypes deliberately
explore allowing inheritance because compatibility was not required.

## Evidence and reproduction

Tested with **CPython 3.14.2, ty 0.0.77, Python 3.14 target**. No plugin, generated
model files, or new package dependency. Existing Pydantic and aiosqlite support
the executable prototype. No Python 3.15-specific behavior was tested or needed.

```sh
uv run python -m typing_probes.model_definitions.check
uv run snektest tests/model_research
uv run ty check
uv run ruff check .
uv run ruff format --check .
```

The research suite contains:

- **112 isolated typing observations**, each with a clean positive control.
- **93 intended diagnostic rejections**, checked at the expected source line.
- **18 accepted counterexamples**, explicitly recorded rather than hidden.
- **One known checker failure**, separated from normal diagnostic rejection.
- **18 runtime tests**, including real SQLite inserts/materialization and one
  existing-model reference test.

Thus the 130 passing research tests mean the observations match, not that every
proposed design is sound. `cases.json` contains the caller programs;
`results.json` contains diagnostics, interpreter/checker versions, and source
hashes. Inputs are created under `.git` because this host's `/tmp` user quota was
exhausted. The runner also imposes a timeout on checker processes.

`runtime.py` implements the two leading designs. Tests against its actual public
signatures are separate from the earlier `.pyi` feasibility probes. Its SQLite
executor binds values, quotes identifiers, and uses hand-written test schemas.
It does not implement a general query compiler, storage codecs, or schema tools.
The internal casts cover validated value storage and retaining a constructor's
row type after runtime class checks; caller tests do not cast away mistakes.

Validation also passed full-repository ty, Ruff lint/format checks, and 1,037 fast
tests using `PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest tests --mark fast`.
The complete database/integration suite was not run.

## Conclusion

I cannot prove there is no better Python design. This pass instead found two
comparable designs that the first pass missed, with specific benefits and costs.

For strict pending/read separation, I would investigate the **shared-field,
two-class model** first. For the shortest declarations, I would compare the
**single-class command-construction model** against actual application code.
Neither needs generation or a type-checker plugin. Neither should be dismissed
before reviewing its construction semantics and remaining integration costs.
