# Follow-up: flatter default declarations

Research for #473, 2026-10-25, continuing from the [first round](README.md).
CPython 3.15.0 / ty 0.0.84; starting research commit `0e10a59`.
All experiments remain static-only. No production declarations or runtime tests
are changed or executed. Names below are illustrative, not agreed spellings.

Maintainer feedback: retain the outer `DatabaseDefault(Integer(), default=...)`
form, but rank it lower for verbosity. This round looks for flatter alternatives
rather than trying to persuade the maintainer to like nesting.

## Important correction to the design space

The earlier omission constraint is about **registered field-specifier calls**,
not every expression that returns a column descriptor.

The [typing specification](https://typing.python.org/en/latest/spec/dataclasses.html#field-specifier-parameters)
defines `default`, `default_factory` and `factory` as recognized arguments to
field specifiers. Without them, a registered field call describes a required
field. But an ordinary descriptor-valued assignment can instead be treated as
a field default. The latter route works with snekql's actual backend models in
these ty experiments.

For example, a helper with this signature, **not registered** in
`dataclass_transform(field_specifiers=...)`, permits omission:

```python
def ServerInteger[T](server_default: T, ...) -> db.GenCol[T]: ...

attempts: db.GenCol[int] = ServerInteger(7)
```

Constructor overrides remain typed, a required ordinary field remains required,
and a mismatched literal default is rejected. The helper is not returning Any
to make the call pass. An additional control registers the *same* helper:
`ServerInteger(server_default=7)` then leaves the field required again, and the
mismatched declaration slips through, reproducing the first-round limitation.

This does **not** make `Integer(server_default=7)` work on the existing registered
constructor. Unregistering all ordinary constructors is not a solution: it
would make required fields omittable too. The viable approach distinguishes
ordinary required declarations from database-supplied declarations.

## Viable flatter shapes

### 1. A server declaration namespace

Candidate public spelling:

```python
name: db.Col[str] = db.Text()
done: db.Col[bool] = db.Integer(default=False)
server_done: db.GenCol[bool] = db.server.Integer(False)
created_at: db.GenCol[db.UtcDatetime] = db.server.Text(db.CurrentTimestamp)
label: db.GenCol[str | None] = db.server.Text("fallback")
null_default: db.GenCol[str | None] = db.server.Text(None)
id: db.GenCol[int] = db.server.Integer(primary_key=True, auto_increment=True)
```

`db.server.Integer(default=False)` also passes; positional versus keyword values
is a readability choice, not a typing blocker. The prototype uses a local
`server` object with typed methods; no actual `db.server` export is added.

This separates ownership through a short prefix. Plain column declarations can
keep Python `default=` and `default_factory=`. Server declarations produce a
pending value when omitted, including IDs with no literal default. The prefix
means **database-supplied**, not necessarily a SQL DEFAULT clause: identity
still uses the backend's ordinary identity settings.

Cost: another declaration namespace and a server variant for each supported
storage primitive. Backend-specific options still need clear, typed signatures.
It must not become an unrelated duplicate model-declaration system.

### 2. Prefixed server constructors

```python
server_done: db.GenCol[bool] = db.ServerInteger(False)
created_at: db.GenCol[db.UtcDatetime] = db.ServerText(db.CurrentTimestamp)
id: db.GenCol[int] = db.ServerInteger(primary_key=True, auto_increment=True)
```

Same mechanism, without an extra namespace. Complete examples use the local
`ServerInteger` and `ServerText` helpers; the `db.` export is only a candidate
spelling. This is shorter than the outer form and makes ownership visible at
the constructor name.

Cost: more top-level names, repeated prefixes across backend storage primitives,
and a naming decision about whether “server” communicates generation clearly
enough. Neither namespace nor prefix is ruled out on typing grounds here.

### 3. A flat ownership selector

```python
done: db.Col[bool] = db.Integer(default=False)
server_done: db.GenCol[bool] = db.Integer(default=False, default_on="database")
created_at: db.GenCol[db.UtcDatetime] = db.Text(
    default=db.CurrentTimestamp, default_on="database"
)
```

The prototype calls these `LocatedInteger` and `LocatedText`. Overloads select
plain versus generated descriptor shapes from a literal ownership argument.
The explicit `default=` argument supplies the field-specifier omission signal.
Wrong default values, wrong descriptor shapes, invalid selector strings, and a
Python factory requested on the database branch are rejected by the probes.

Cost: another argument and a mode that callers must understand. It chooses the
owner of a *single* supplied default rather than independently declaring two
defaults. That follows from this shape; it was not an upfront coexistence rule.
IDs retain the existing pending-marker declaration in this prototype: the
selector alone does not fix omission when no `default=` value is provided.

## Attractive forms that did not survive the controls

| Attempt | What happens in the tested signatures |
| --- | --- |
| A registered descriptor class with `Integer.server_default(7)` | Server declaration works, but ordinary `Integer()` fields incorrectly become omittable |
| A callable factory object with a `server_default` method | Same loss of required-field checking, despite registering the instance and its `__call__` method |
| Registered function `Integer().db_default(7)` | ty treats the inner registered call as `dataclasses.Field`, so the chained method is an `unresolved-attribute` error |

The first two are particularly misleading: a clean constructor call is not
sufficient evidence of success if it also accepts missing required inputs.
These failures are recorded as observations of ty 0.0.84 and these signatures,
not proofs that no class/callable/fluent design could ever work.

## Coverage and limits

The three viable alternatives pass the shared full-model consumers for both
backend namespaces: Boolean and integer literal defaults, UTC clock defaults,
nullable literals and NULL defaults, explicit overrides, ordinary Python
values and factories, required nullable fields, exact Pending/Row field types,
and exact INSERT RETURNING result types. Namespace and prefix variants also
exercise generated IDs **without** an explicit pending marker. Prefix and
namespace examples use the actual existing backend Model, not a new model base.

Scalar probes reject mismatched literal declarations. Dedicated selector probes
also check the Python-default and Python-factory branches and reject a generated
result assigned to an ordinary `Col` field. Required-field controls remain in
place; blocked designs do not count as viable just because they accept omission.

The new templates are `flat_declarations.py.txt`, `selector_modes.py.txt`, and
`fluent_blocked.py.txt`. They are never imported or executed. The fixture
functions' implementation bodies raise `NotImplementedError`; overload
implementations use Any only behind typed public overload signatures.

Not established: runtime lowering, SQL/DDL/verification behavior, actual factory
timing, schema compatibility, all physical storage types, foreign keys, or
human preference beyond the maintainer's feedback on nesting. No new coexistence
policy or migration policy is chosen. The first-round runtime acceptance
criteria and compatibility cautions still apply.

## Current shortlist

- Bring namespace and prefixed-constructor forms forward for readability review.
- Keep the flat selector and the existing tagged-default family in contention.
- Retain the outer form as a lower-ranked fallback, per maintainer preference.
- Do not adopt the class/callable/chained prototypes merely for their attractive
  syntax; their current static failures matter.

The next useful comparison is whole model declarations using the first two
forms, including IDs and clocks. Typing no longer forces an outer wrapper or
an explicit pending sentinel for every database-supplied value.

## Reproduce

```sh
uv run snektest tests/research
uv run ty check
uv run ruff check .
uv run ruff format --check .
```

**42 positive/challenge pairs pass** (18 first-round, 24 follow-up), across both
backends, in approximately six seconds locally. Some pairs intentionally
record a blocked design's exact failure or accepted invalid declaration; the
count is not a claim that every investigated shape is usable. No database
runtime suite is run.
