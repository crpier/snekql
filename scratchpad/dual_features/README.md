# Dual-class models across snekql features

Local research, continuing the model-interface questions associated with #396.
No production changes, new issues, PRs, commits, or checker plugins.

For a single read-through Python file, start with [`example.py`](example.py).
It defines the model pairs, uses the query/write interfaces, and records exact
inferred types. The executable examples run against in-memory SQLite. Static-only alternatives
remain in the preserved explicit-source tour and research probes.

The query-interface follow-up now uses direct columns/models, class-local FK
declarations, explicit `.references(...)` joins, transaction-owned execution,
and checked `.into(...)` materialization. Both tours include RETURNING and SQLite
ON UPDATE CASCADE. Its alternatives, 158 typing observations, and runtime evidence
are documented in
[`../dual_queries/README.md`](../dual_queries/README.md). The original source-heavy
tour is preserved in [`example_explicit.py`](example_explicit.py). The feature
research and reference snippets below describe that earlier interface.

```sh
uv run ty check scratchpad/dual_features/example.py
uv run python -m scratchpad.dual_features.example
```

For the current public snekql equivalent, read
[`example_current.py`](example_current.py). It keeps the scenario/function names
where possible and spells out differences instead of importing prototype helpers.
Its SQLite runner includes named nullable and ten-field projections; only the
MariaDB and additional typing examples remain under `TYPE_CHECKING`.

```sh
uv run ty check scratchpad/dual_features/example_current.py
uv run python -m scratchpad.dual_features.example_current
```

## Verdict

The dual-class foundation accommodates foreign keys, scoped queries, aliases,
nullable joins, typed projections, generated-column writes, and upserts. I found
no need to put lifecycle generics back into application model declarations.

It does **not** remove the need for query-scope, readiness, and backend-family
types. Those facts describe operations, not whether a Python row has generated
values. Keep those coordinates private, much as current snekql already does.

My preferred combination from these experiments:

- Immutable input/read inheritance, with constructor-based insert commands.
- An explicit marker distinguishing queryable read classes from input classes.
- Separately declared, typed relationship objects. Resolve them after both row
  classes exist, rather than repeating FK targets in annotations and initializers.
- Invariant column ownership, distinct alias identities, and nullable source
  views that lift projected values to `T | None`.
- Incremental variadic projections, with checked Python result constructors.
- Existing private readiness and backend-family principles.
- Existing logical-type/physical-storage separation and codec machinery.

Several improvements here could also be applied to the current model design.
Dual classes make the row types simpler; they are not what makes variadic
projections or a better upsert contract possible.

## Evidence and artifact boundaries

Run everything local to this experiment:

```sh
bash scratchpad/dual_features/run.sh
```

Environment: CPython 3.14.2, ty 0.0.77, Python 3.14 target. No 3.15-only feature.
Original feature-research baseline: `62f6665`. `records.py` started as a copy of
the earlier model prototype. The query-interface follow-up adds read operators,
field-local relationship descriptors, deferred annotation handling, and read-class
source/selection bridges; its baseline is
`f7ac4e5`. Production descriptors and query code were not modified.

- **91 isolated typing observations**, each with a clean positive control.
  Exact inferred-type assertions accompany the major result-shape claims.
- 73 expected diagnostic observations and 18 accepted observations. Some
  diagnostics demonstrate undesirable false positives or unsupported operations,
  not successful safety guarantees. Accepted cases include both capabilities and
  counterexamples.
- **41 runtime tests**, including seven original current-snekql controls, three
  current-API companion result/cascade tests, and real SQLite joins, generated values,
  FK enforcement, composite FK behavior, codecs, and upserts.
- **1,075 existing fast tests passed.** No full database/integration suite or
  MariaDB server run.
- Full-repository ty, Ruff lint, and formatting checks passed.

Files:

- `models.py`: actual dual-class declarations.
- `runtime.py`: executable SQLite subset and alternative interfaces.
- `options.pyi`: **static-only alternatives**, not implementations.
- `current.py`, `test_reference.py`: current snekql controls.
- `cases.json`, `header.py.txt`, `check.py`, `results.json`: independent callers
  and compact observations. A rejection must occur in the added challenge, not
  in its control or an unresolved import.
- `test_relations.py`, `test_queries.py`, `test_writes.py`: runtime observations.

The prototype is deliberately incomplete. It has no production schema registry,
full storage metadata, migration/verification integration, complete expression
language, correlated subqueries, CTEs, unions, streaming, or shared-backend runtime.
Its domain and presence-witness inspection covers the tested annotations, not
current snekql's complete alias/nullability handling. Its implementation carriers
are not hardened public constructors. The tested contracts assume callers use the
supplied factories. Localized casts and value
erasure inside materialization are explicit trust points, not caller workarounds.

## 1. Foreign keys

### The row declarations

A relationship field can remain an ordinary scalar field:

```python
class NewEntry(Record):
    id: Field[int | Omitted] = field(default=OMIT)
    account_id: Field[int | None] = field(default=None)
    note: Field[str] = field()


class Entry(NewEntry, ReadRow):
    table_name = "entries"
    id: Field[int] = required()
    create = insert_using(NewEntry)


entry_account = relationship(Entry.account_id, Account.id)
# Relationship[Entry, Account]
```

These are executable prototype declarations, not complete production schema
specifications. The tests hand-author physical SQLite column declarations.

`ReadRow` is an extra framework base, not a third application data class. Without
such a distinction, a broad `select(type[Record])` would also accept `NewEntry`
and promise an input-shaped result. The tested `source(NewEntry)` is rejected.

### Options compared

| Option | Observation | Preference |
| --- | --- | --- |
| `ForeignField[Account, int] = foreign(Account.id)` | Good constructor and join-use types. A mismatched initializer targeting `Other.id` still passes ty under dataclass transformation. | Familiar, but retains duplicated facts and a declaration hole. |
| Ordinary assignment to `ForeignField[Account, int]` outside a transformed model | Rejects the mismatched target. | Confirms that the transformed declaration, not the generic descriptor alone, changes checking. |
| `nullable_reference(Entry.account_id).to(Account.id)` | Checks value compatibility, captures the target, works at runtime. | Sound tested alternative, but asks callers to spell nullability. |
| One function using unions of nullable/nonnullable column types | Rejects some valid nullable/nonnullable combinations. | Rejected as the primary interface. |
| Four overloads covering nullable/nonnullable sides | Accepts the tested valid combinations and rejects wrong domains. | Preferred implementation behind `relationship(source, target)`. |

The preferred function returns `Relationship[From, To]`. Its public protocol
exposes relationship operations, not `Any`-valued columns. The value coordinate
has done its job once the factory checks compatibility; callers do not need it
just to declare a join.

```python
accounts = source(Account)
entries = source(Entry)

query = (
    select(entries)
    .join(accounts, on=entry_account.on(entries, accounts))
    .add(accounts.column(Account.name))
    .all()
)
```

Passing `source(Other)` as the relationship's target is a type error. A wrong
logical domain fails at the factory even for the dynamic runtime caller test.

Declaring relationships after row classes also supports self-reference without
an input class mentioning its not-yet-defined read subclass. Mutual relationships
can be assembled after both class pairs exist. Self-reference was executed as a
metadata test; a cyclic schema/insert workflow was not implemented.

### Current comparison

Current `FKCol[Account, int] = ForeignKey(Account.id)` preserves target types when
building `.references(...)`, but a contradictory initializer also passed ty.
In the current runtime control, the class definition succeeded and **schema
planning through `scaffold` rejected the mismatch**. Do not describe that tested
check as a class-definition check.

`enforced=False` in the prototype keeps the typed join relationship without
emitting a constraint. Actual SQLite tests distinguish enforced and soft refs.

Important unresolved work: target candidate keys, storage compatibility, delete
and update actions, backend identity, and metadata freezing. A matching Python
value type does not establish those facts. The prototype's DDL helper does not
replace current snekql's schema validation.

## 2. Composite references and ID domains

I tested both:

```python
columns(Entry).add(Entry.id).add(Entry.note).references(
    columns(Account).add(Account.id).add(Account.code)
)
```

and paired relationships:

```python
edge = composite(
    relationship(Entry.account_id, Account.id),
    relationship(Entry.note, Account.code),
)
```

The first is a static-only `TypeVarTuple` contract. It catches arity, owner, and
incompatible positional domains. Nullable source membership was accepted in the
tested pack case. It cannot identify swapped same-typed fields by meaning.

The second is executable. It fixes each source/target correspondence together,
handles scalar nullability through the same overloads, and retains the source and
target table types while erasing heterogeneous value coordinates internally.
Runtime checks reject repeated members and mixed enforcement policies.

I prefer pairs for authoring relationships. They are harder to misalign and the
same declarations serve scalar and composite cases. Packs remain a reasonable
option for reusable typed key groups.

SQLite tests verified that a composite constraint rejects values drawn from two
different parent rows, even when each value exists separately. A NULL member
bypasses the constraint under SQLite's ordinary composite-FK semantics. The tests
supply the required parent composite unique key explicitly.

Neither approach prevents this with plain integer IDs:

```python
Entry.create(account_id=other_row.id, note="wrong domain")
```

I compared generic `Key[Account, int]` wrappers with `NewType` IDs. Both reject
cross-domain values statically. The wrapper remained static-only. `NewType` IDs
also passed an actual generated-ID SQLite round trip using the scalar codec.
I would offer nominal IDs as an opt-in, not require relationship objects as field
values. `NewType` does not provide runtime provenance or prove row existence.
Both lifecycle-generic and dual-class models can use it.

## 3. Joins, aliases, and query scope

### Preserve both comparison owners

The prototype's column-to-column equality returns
`Predicate[LeftScope | RightScope]`. Conjunction also accumulates owners. This
rejects an unrelated right operand in WHERE and an unavailable source in ON.

Current snekql preserves the left owner for these comparisons and validates the
right operand during compilation. The runtime control confirmed that rejection.
Its behavior supports enclosing-query correlation. The prototype has **no
correlated subqueries**, so its stricter local rule is not a demonstrated
replacement for current correlation handling.

### Alias alternatives

| Option | Observation |
| --- | --- |
| SQL names only, no type coordinate | Manager/reviewer mixups pass. |
| Generic alias name bounded by `str` | ty widens the name to `str`; mixups still pass. |
| Alias name bounded by `LiteralString` | Direct literals retain exact `Literal["manager"]` identities and reject reviewer mixups. |
| A broadly annotated `LiteralString` variable | Exact identity is lost; different aliases can share the same static scope. |
| Nominal role classes | Reliable static distinction even when SQL names are generated. Same-role misuse still needs runtime checks. |

I would retain current nominal role markers as the general contract. The tested
`named_alias(Account, name="manager")` is a useful optional shortcut for literal
names under this ty version, with the limitation above documented.

One runtime counterexample improved the prototype: an alias object reusing a
role could name another joined SQL alias. Checking only model/role membership
accepted it and read the wrong role's data. Scope tokens now include the SQL name,
and joins separately check duplicate role identities and SQL names. A nominal
scope type does not remove runtime identity checks.

## 4. Nullable projections and result shapes

Current model-select left joins produce optional right rows correctly. Current
positional projection-select left joins are deliberately rejected because their
result coordinates cannot selectively add nullability. Named
`select(Model).left_join(...).project(Result, **bindings)` does work: the result
fields must accommodate NULL, checked during query construction rather than
through a statically nullable source view. `example_current.py` executes this
alternative.

The prototype makes the nullable source explicit:

```python
class EntryRole:
    pass


accounts = source(Account)
entries = outer(Entry, EntryRole, name="entry")

query = (
    select(accounts)
    .left_join(
        entries,
        on=accounts.column(Account.id).eq_nullable(entries.column(Entry.account_id)),
    )
    .add(accounts.column(Account.name))
    .add(entries.column(Entry.note))
    .all()
)
# await query.fetch(connection): list[tuple[str, str | None]]
```

The nullable source has `Outer[Alias[Entry, EntryRole]]` scope. A nonnullable view
with the same row and role is not accepted in its place. Merely making a getter
return `T | None` while keeping the old scope would leave an escape through the
old nonnullable view.

Whole-row selection works too:
`entries.row(present=Entry.id)` has result `Entry | None`. It needs a nonnullable
presence witness to distinguish absence from nullable data. All-nullable tables
would need a synthetic presence marker or another policy, not guessed absence.

For accumulated results I compared nested pairs with flat variadic projections.
Nested pairs need little typing machinery but change three-way results to
`((Account, Entry), Other)`. Incremental `.add(...)` preserves a flat tuple.
The ten-slot mixed projection control retained every slot's exact type; current
SQLite positional `select(...)` overloads stop at eight. Current named `.project`
results are not subject to that limit. The companion's ten-field Pydantic result
is type-checked and executed, with binding labels/domains checked at runtime.

The prototype always returns tuples before mapping, including one-slot tuples.
That differs from current scalar/model selection ergonomics. It also requires
joins before adding their columns. These are costs, not hidden compatibility.

A final `.map(ResultClass)` checks constructor arity and positional domains.
`str`, a broader accepting converter, works too. The mapping is terminal Python
materialization and requires an executable query. It is not a SQL function and
cannot be embedded as a transformed scalar subquery. CTEs, SQL labels, named
bindings, and arbitrary Python transformations need separate treatment.

## 5. Writes, generated values, and upserts

### An inheritance regression to avoid

`Account` subclasses `NewAccount`. Therefore an interface accepting a
`NewAccount` instance also accepts an `Account` instance. The direct-input insert
alternative demonstrated that acceptance. Current pending-only insert rejects a
fetched model statically.

The executable path takes `Account.create(...) -> Insert[Account]` commands,
not input-row instances. Passing the read row itself to that constructor command
is rejected. If a future interface also accepts input objects, choose an explicit
runtime exact-input check, different inheritance arrangement, or accept that
weaker static contract. Do not promise exact input-class matching from subtyping.

### Preserve useful write behavior

- Generated and primary-key columns remain update-assignable. Row immutability
  does not make stored columns immutable.
- Wrong-owner assignments and input-class columns are rejected for read-table
  updates.
- Both designs reject an omission marker used as an ordinary generated-column
  update value in the tested callers.
- Four-state assignment/scope readiness supports SET-first and WHERE-first order.
  The nominal staged alternative forces an order and multiplies builder classes.
  I prefer the existing hidden-state principle.

### Separate conflict-only assignments

`attempted(Account.name)` is a distinct capability accepted by conflict updates
but not ordinary updates. Current `.to_inserted()` returns the general assignment
contract, so that misuse passes ty and fails during compilation.

The SQLite prototype returned the existing identity after a conflict update.
`ignore_conflict(...)` returns `Account | None`. Current `DoNothing.returning()`
passes the checked construction call but is rejected during compilation. Optional
returning is a possible query-interface improvement, independent of dual classes;
MariaDB behavior was not implemented or assumed equivalent.

A static-only typed server-expression experiment also rejects assigning
`Server[datetime]` to an integer column. Current `.to(CurrentTimestamp)` accepts
that call statically. This says nothing about arbitrary SQL expression correctness
or whether a backend supplies the declared logical value.

## 6. Logical types, storage, and backend families

### Keep codec derivation separate from lifecycle

UUID, datetime, constrained Decimal, and nominal integer IDs survived actual
SQLite materialization. Wrong UUID wire strings are rejected by the typed
expression interface, and UUID columns do not gain `.like()` merely because their
physical storage is TEXT. Nullable string LIKE remains available.

An explicit `TypedCodecField[int] = codec_field(uuid_codec)` declaration passed
ty under dataclass transformation. Adding a codec type argument does not by
itself solve annotation/initializer disagreement. Prefer the current single
logical annotation plus storage-derived codec design unless a genuinely different
codec contract requires an explicit choice.

The real Decimal counterexample matters: inserting `Decimal("12.50")` as TEXT
and querying for `Decimal("12.5")` missed the row. Equal Python values need not
have equal wire forms. Using current `CanonicalDecimal` as the prototype's
logical annotation repaired equality. Current snekql also emits lexical warnings;
the minimal prototype does not reproduce those safeguards.

Do not replace current codecs with this experiment's short JSON-mode adapter.
JSON markers, BLOBs, native MariaDB storage, canonical ordering, precision limits,
integer bounds, nonfinite values, and codec-compatible FK storage remain real
requirements.

### Preserve backend witnesses

Static-only `FamilyTable[Family, Row]` and `FamilyQuery[Family, Result]` experiments
reject mixed joins and wrong-family transactions when namespaces pin the family.
Current runtime carriers already apply that principle.

Literal family inference was preserved in the tested direct call. A helper that
accepts and returns a broad `str` erased the distinction and admitted mixed joins.
Use pinned namespace types or direct private witnesses, not a hope that a dynamic
string remains a singleton type.

The dual-class executable subset is SQLite-only and does not propagate this
family coordinate throughout its columns or relationships. Combining family,
scope, and readiness in one complete dual-class engine remains unimplemented.

## Schema and inheritance work still needed

Two Python classes must describe one physical table. The read refinement must
change constructor availability without dropping storage, FK facts, server
expressions, defaults, keys, indexes, or logical validators. The input class
must not become a second schema target just because it has column descriptors.

Production work would need an explicit table-finalization/registration rule:

1. Establish the input/read pair and check their field correspondence.
2. Resolve typed relationship declarations after the relevant classes exist.
3. Validate candidate keys, physical storage, actions, backend identity, and
   composite ordering with the existing schema machinery.
4. Freeze one authoritative table description used by queries and Scaffold.

These experiments do not choose whether that description lives on the read class
or in a separate table object. Nor do they solve required-field extension and
factory rebinding beyond the prior model experiment. The row constructor shape
is promising; it is not a complete schema-interface proposal.

## Review order

Start with `models.py`, then the relationship and nullable-source examples above.
`runtime.py` contains the executable mechanisms. `options.pyi` and `cases.json`
retain the unsuccessful alternatives so their limitations remain reproducible.

Current-design references:

- [Typing guide](../../docs/typing.md)
- [Storage primitives and derived codecs](../../docs/adr/0005-storage-primitive-constructors-with-derived-codecs.md)
- [Generated columns remain writable](../../docs/adr/0006-columns-are-not-immutable.md)
- [Private backend witnesses](../../docs/adr/0014-private-backend-family-witnesses.md)
- [Private query readiness](../../docs/adr/0016-private-query-readiness-typestate.md)
- [Earlier local endpoint comparison](../crud_endpoints/README.md)
