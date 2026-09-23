# Alternative typing foundations, first pass

Research for [issue 396](https://github.com/crpier/snekql/issues/396). Throwaway
experiments, not proposed production interfaces. CPython 3.14.2, ty 0.0.77,
Python 3.14 target. No Python 3.15-only feature was needed.

## Findings

The strongest immediate result is **incremental projections with checked result
constructors**. This can be explored independently of a model redesign.

For model definitions, a **generated facade over an ordinary dataclass** has the
strongest typing result in this pass. It removes lifecycle parameters and keeps
required insert arguments, generated IDs, column value types, and named query
results. The cost is a generation step and generated files.

**Separate dataclass input/read rows with attribute selectors** also work. They
avoid generation and let applications reuse ordinary data classes, but queries
are more verbose and selector bodies need runtime restrictions. Worth pursuing
if those benefits matter; not my default recommendation.

Fetched-only descriptor models with assignment-based inserts are not shortlisted
on their own. Their shorter declarations are real, but missing required insert
fields go unchecked. The other designs address that weakness.

These are feasibility results, not a recommendation to replace snekql yet.

## What actually ran

- 40 independently checked caller contracts, each with a clean positive control.
- 34 invalid examples rejected at the intended line, with no unrelated errors.
- Five deliberately accepted counterexamples, recorded as limitations rather
  than successful static rejections.
- One additional positive-only ten-column inference check.
- Six runtime feasibility tests for projection ordering/materialization and
  attribute-selector capture/rejection.
- One generator freshness test.

All caller tests assert exact query/result types where inference is the subject.
Invalid examples are added one at a time, rather than considering any diagnostic
in a large broken file a success. Unresolved imports/references cannot count as
an intended rejection. `results.json` records diagnostics, interpreter/checker
versions, and source hashes.

`core.py` executes projection construction and applies result constructors to
already-decoded values. It is **not a SQL compiler or database runtime**.
`fetched.pyi`, `records.pyi`, and `generated.pyi` are static contracts, with no
matching CRUD runtime implementations. Do not try to execute the `.py.txt`
consumer programs. The executable tests distinguish the mechanisms we exercised
from contracts checked only by ty.

No caller-side casts, `Any`, or ignores were used to make the typing examples
pass. Internally, the selector capture deliberately substitutes a token proxy
for a row, and positional materialization casts already-decoded values to its
recorded tuple shape. These are explicit runtime trust points, not proof that
SQL decoding works.

## 1. Incremental projections and checked constructors

```python
@dataclass
class Summary:
    name: str
    total: int


query = (
    columns(Account.name).add(Account.id.count()).map(Summary).group_by(Account.name)
)
# Query[Account, Summary]
```

The builder carries `Projection[Owner, *Values]`. Each `.add(Item[Owner, T])`
returns `Projection[Owner, *Values, T]`. Finishing with `.query()` produces
`Query[Owner, tuple[*Values]]`; `.map()` accepts `Callable[[*Values], Result]`.
There is no per-width overload table.

Observed:

- Ten alternating `str`/`int` slots keep their exact tuple type.
- Wrong source owners, constructor argument types, and constructor arity fail.
- `COUNT` contributes `int`; `SUM(int)` contributes `int | None`.
- Mapping a nullable sum into a required `int` result field fails.
- An aggregate predicate cannot be passed to row-level `.where()`.
- The runtime preserves expression order and invokes the actual checked
  constructor, producing a `Summary`.

Keyword-only result constructors need a small lambda:

```python
.map(lambda name, total: KeywordSummary(name=name, total=total))
```

The lambda parameters are inferred. Swapping the two differently typed values
is rejected. Passing a keyword-only constructor directly is also rejected.

This offers something beyond today's named projection contracts. Current
`project(Result, **bindings)` types the result but checks the binding names and
logical domains at runtime, as documented in `docs/typing.md`. The constructor
approach catches the tested argument-shape mistakes statically.

Costs and limits:

- Chained syntax instead of a flat `select(a, b, c)` or named bindings.
- Positional mapping can still swap two same-typed fields. Keyword lambdas make
  the mapping visible but do not prove semantic intent.
- No automatic output-label derivation for CTEs or named SQL outputs.
- The prototype allows selecting an ungrouped column alongside an aggregate.
  It does not prove SQL grouping legality.
- Only one source owner is implemented. Join scope, left-join null extension,
  aliases, backend identity, and query readiness propagation remain untested.
- Dataclass construction is not runtime value validation. A real implementation
  must preserve decoding and any desired result validation separately.

**Next experiment:** adapt this projection shape to existing expressions and
probe joins/null extension before choosing it over today's projection methods.

## 2. Generated facade from one dataclass

Source declaration, `schema.py`:

```python
@dataclass(kw_only=True)
class Account:
    age: int
    id: int = field(metadata={"generated": True})
    name: str
    nickname: str | None = None
```

The generator emits typed columns and a keyword-only insert signature:

```python
accounts.insert(name="Ada", age=30)  # Write[Account]
accounts.insert(name="Ada", age=30, id=100)  # Explicit ID also allowed
accounts.select()  # Query[Account, Account]
accounts.update().set(accounts.age.to(31)).where(accounts.id.eq(1))
accounts.delete().where(accounts.id.eq(1))

columns(accounts.name).add(accounts.id.count()).map(Summary)
```

Observed:

- Required insert arguments and their value types are checked.
- Unknown insert keywords are rejected.
- Omitted generated IDs are allowed on insert. Explicit `None` is rejected.
- Read-row construction still requires `id: int`.
- Nullable column types survive selection and assignment.
- Aggregate result constructor checks work with the generated columns.
- A real generator derives the facade from dataclass fields and annotations.
  A test checks that the checked-in output matches regeneration.

The prototype generator supports builtin scalar types and unions only. It emits
one example facade, not a general schema-generation tool. Storage declarations,
custom logical types, runtime facade construction, migrations, and declaration
errors are not implemented.

The typing benefit comes from spelling out what Python cannot generally derive
in library signatures: a different keyword constructor for insert and a typed
column namespace for a row class. There is one handwritten field declaration,
but generated code must be kept current in the editor and CI.

**Verdict:** strongest model candidate if generation is acceptable. Before
recommending it, build a small actual CRUD runtime and test schema-change
regeneration and stale-output detection.

## 3. Ordinary dataclasses with selectors

```python
@dataclass(kw_only=True)
class NewAccount:
    age: int
    name: str
    nickname: str | None = None


@dataclass(kw_only=True)
class Account(NewAccount):
    id: int


accounts = Table(Account, NewAccount)

accounts.insert(NewAccount(name="Ada", age=30))  # Write[Account]
accounts.select()  # Query[Account, Account]
name = accounts.column(lambda row: row.name)
account_id = accounts.column(lambda row: row.id)
accounts.update().set(name.to("Grace")).where(account_id.eq(1))
accounts.delete().where(account_id.eq(1))
columns(name).add(account_id.count()).map(Summary).group_by(name)
```

The library stores explicit read/input types on the table, rather than changing
one generic model's lifecycle state. Sharing handwritten fields through
inheritance avoids repeating them in this example. Separate unrelated dataclasses
would also work, but their relationship would need runtime validation.

Observed:

- Missing or mistyped insert fields fail through the ordinary constructor.
- This input class cannot accept an explicit generated ID. Supporting overrides
  requires changing the input contract; the generated-facade design avoids that.
- Unknown selected attributes and incompatible assignments fail.
- Optional columns remain optional. Unrelated row owners cannot mix in updates
  or deletes.
- Named aggregate results work with the same projection builder.

The selector's type is `Callable[[Row], Value]`. That checks row attributes and
infers the value; it **does not mean “direct column reference.”** Both
`lambda row: 42` and `lambda row: row.name.upper()` pass ty. The runtime experiment
captures direct attributes without source parsing, rejects these tested cases,
and rejects Python boolean shortcuts rather than silently dropping operands.
It is not a general Python-to-SQL translator or a proof against every callback.

Two distinct tables using the same row class are indistinguishable statically
in this prototype. Runtime source identity or separate nominal scope types are
needed for aliases and self-joins.

**Verdict:** conditional candidate for ordinary-dataclass reuse without generation.
The selector repetition is a real ergonomic cost. Do not trade today's column
syntax for this without reviewing larger query examples.

## Not shortlisted: fetched-only descriptors with assignment inserts

```python
class Account(Model):
    id: Field[int] = field()
    name: Field[str] = field()
    age: Field[int] = field()


insert(Account, Account.name.to("Ada"), Account.age.to(30))
```

Exact fetched fields, model selection, typed assignments, source ownership, and
aggregates all work without lifecycle parameters. A staged update builder also
rejects filtering an update before supplying an assignment.

But `insert(Account, Account.name.to("Ada"))` passes despite omitting required
`age`. A generic list of typed assignments cannot express the model's required
field set here. This trades away a useful guarantee for a shorter declaration.
Recovering it requires an explicit input contract or generation, which leads
back to the stronger candidates above.

## Reproduce

```sh
uv run python -m typing_probes.foundations.generate
uv run python -m typing_probes.foundations.check
uv run snektest tests/research
uv run ty check
uv run ruff check .
uv run ruff format --check .
```

The checker command rewrites `results.json`. Temporary inputs live under `.git`
because this host's `/tmp` user quota was exhausted. No production files change.

Validation completed for this pass:

- Research suite: 47 passed.
- Existing plus new fast tests: 1,032 passed with
  `PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest tests --mark fast`.
- Full-repository ty, Ruff lint, and formatting checks passed.

The first fast run without `PYTHON_CONTEXT_AWARE_WARNINGS=1` hit five existing
raw-query tests requiring that interpreter flag. Re-running with the documented
flag passed. The complete database/integration suite was not run.

## Remaining research

Model/CRUD contracts and an early aggregate test are covered, not most of the
library. Next priorities are join ownership/nullability, named SQL output labels
and CTEs, generated/defaulted input variations, helper annotations, backend
identity, readiness, and runtime validation. No claim about those features is
implied by the passing first-pass probes.
