# Streamlined dual-class queries

Local follow-up to the model-interface research in GitHub issue #396. Baseline
`f7ac4e5`, CPython 3.14.2, ty 0.0.77, Python 3.14 target. No plugins, production
changes, commits, or publication. The historical issue is context, not
an implementation ticket for a production change.

## Recommendation

Use direct model/column selection, invariant source witnesses, separate available
and required source coordinates, and a tuple-specific query class for checked
constructor mapping. Keep reusable variadic bundles for wider projections.
Declare relationships with their fields, and let transactions consume completed
queries. The application tour no longer uses module-level relationship constants
or public query execution methods.

```python
select(Account).where(Account.id.eq(account_id))

await transaction.fetch_all(
    select(Entry.note, Account.name)
    .join(Account, on=Entry.account_id.references(Account.id))
    .all()
)

select(Account.name, Account.balance).all().into(AccountSummary)
```

This keeps the shorter query spelling while adopting the requested declaration
locality and transaction ownership. It removes ordinary
`source(...)`, `.column(...)`, and per-field `.add(...)` ceremony without giving
up the tested source, readiness, and nullable-role checks. Alias columns still
use `.column(Model.field)`, as current snekql does.

The updated application tour is
[`../dual_features/example.py`](../dual_features/example.py). The earlier version
is preserved in [`example_explicit.py`](../dual_features/example_explicit.py), and
[`example_current.py`](../dual_features/example_current.py) remains the current
snekql comparison.

## Why the second pass mattered

The first executable candidate had a single `Query[Result]` implementation and
put checked positional mapping on `columns(...).into(factory)`. That worked but
made ordinary constructor mapping unnecessarily indirect.

Two tempting simplifications failed under ty:

- A single variadic query class with scalar/tuple `fetch` overloads inferred exact
  direct results, but failed assignment to a clean `Select[tuple[...]]` helper
  contract. The single-model helper control passed.
- A result-only query with a constrained generic-self tuple unpacker accepted
  annotated factories, but lost lambda input types. An invalid lambda member
  access passed. A simpler result-only class without scope/readiness coordinates
  inferred the lambda correctly, so this is not a universal failure of unpacking.

The final `TupleQuery` inherits the ordinary result carrier with
`Result = tuple[*Values]`. Its private execution protocol needs no scalar/tuple overloads. It keeps
`Values` on the class, so `.into(factory)` gets exact callback input types.
Four fluent overrides preserve those slots through WHERE, ALL, JOIN, and LEFT
JOIN. SQL compilation and decoding still live in the shared implementation.

This adds internal typing code, not another application concept. Both scalar and
tuple queries satisfy the same result-only `Select[Result]` contract.

## Interface choices

| Approach                            | Observation                                                                                             | Decision                                                          |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| Explicit source-based prototype     | Strong tested scopes, but wrappers repeat in ordinary queries                                           | Keep as reference                                                 |
| Direct columns/models               | Exact values and shorter calls; source requirements survive later joins                                 | Preferred default                                                 |
| Model-first `.project(...)`         | Same guarantees; makes the root table explicit when the desired output comes only from a joined source  | Supported alternative                                             |
| Reusable `columns(...).add(...)`    | Ten slots retain exact types; `.into` checks factories before query construction                        | Keep for wide/reused projections                                  |
| Bare `type[Other]` join argument    | Inference widened `Other` to include an unrelated predicate owner                                       | Reject that signature                                             |
| One packed scalar/tuple query class | Direct inference worked; tuple helper contract failed                                                   | Prefer separate tuple carrier                                     |
| Generic-self result unpacker        | Scopeful version lost lambda parameter types and accepted invalid member access                         | Do not expose it                                                  |
| Named `**bindings`                  | Correct output class, but wrong labels and domains passed ty                                            | Not equivalent to checked constructor binding                     |
| Row-selector callbacks              | Exact output tuples, but accepted string transformations and constants that the capture runtime rejects | Not the default                                                   |
| Alias facade returning `type[Row]`  | Concise `.name`, but loses alias identity; nullable facade cannot lift field types                      | Reject                                                            |
| Per-model generated alias facade    | `.name` can retain exact role and value types                                                           | Credible optional generator, not necessary for the core interface |
| `alias[Model.field]`                | Same tested types as `.column(Model.field)`                                                             | Syntax choice only; retain familiar `.column`                     |

The keyword-binding, generated-facade, and indexed-alias alternatives are
**static specimens** in `options.pyi`, not production implementations or a tested
code generator. Current snekql's named projections already have executed SQLite
controls in the companion example. Their keyword/domain validation is runtime,
not the positional static contract demonstrated here.

`capture.py` actually executes guarded one-field and tuple callbacks. Its runtime
rejects `.upper()` even though the callback type-checks. The proxy cast is an
explicit trust point. This is direct-field capture, not Python-to-SQL, and it
does not prevent callback side effects before validation.

## Reading the preferred interface

### Ordinary selections

```python
select(Account).all()  # Account
select(Account.name).all()  # str
select(Account.name, Account.id).all()  # tuple[str, int]
```

The first selection supplies FROM. Other selected tables are requirements, not
implicit joins. This incomplete plan cannot be passed to transaction fetch
methods or returned under an executable helper contract:

```python
select(Entry.note, Account.name).all()  # Account has not been joined.
```

The builder may exist while incomplete. A subsequent explicit join satisfies the
requirement. WHERE can come first if its own sources are already available.
There is no correlated-query exception in this bounded prototype.

Joins do not append output fields. Use `select(Entry, Account).join(...)` when
both model objects are wanted. This differs from current model-select joins but
makes result shape independent of join order and the reason for joining.

### Result mapping

```python
select(Account.name, Account.id).all().into(Summary)

select(Account.name, Account.id).all().into(
    lambda name, number: Summary(name=name, number=number)
)
```

Both calls check domains and arity. The lambda also checks keyword names, with
precisely inferred parameter types. `.into` is terminal materialization and
requires an executable tuple query. It does not create an SQL expression.

`.map(factory)` instead passes each complete result as **one** Python value.
This remains useful for scalar/model results and tuple-aware Python functions.
For a single-field positional constructor, either map the scalar result or use
an explicit one-slot `columns(...)` bundle.

Repeated result definitions can be bound before constructing queries:

```python
summary = columns(Account.name, Account.id).into(Summary)
select(summary).all()
```

A mapped projection is not a comparable scalar. Its constructor runs only during
materialization. Compatible field types do not prove semantic intent: swapping
two string-valued fields still passes.

### Wide projections

The short `select`, `project`, and `columns` spellings have one-to-four-argument
overloads. This is a prototype shorthand limit, not a SQL or result-width limit.
There is no broad fallback overload that silently erases extra arguments.

```python
details = columns(Account.id, Account.name, Account.code, Entry.id).add(Entry.note)
select(details).join(Entry, on=Entry.account_id.references(Account.id)).all()
```

`.add` has no arity ceiling. Ten-slot results and ten-argument constructor lambdas
are checked. More convenience overloads could be supplied independently.

### Relationships belong in model declarations

```python
class NewEntry(Record):
    tenant_id: Field[int] = field(default=1)
    account_id: ForeignField[Account, AccountId | None] = foreign(
        Account.id, default=None, on_update="CASCADE"
    )
    __foreign_keys__: ClassVar = (
        ForeignKeyConstraint(
            tenant_id,
            account_id,
            references=(Account.tenant_id, Account.id),
            on_update="CASCADE",
        ),
    )
```

The read class inherits the declaration. No `ENTRY_ACCOUNT` constant is needed.
`enforced=False` declares a typed soft reference without a database constraint.
The input constructor receives an ordinary scalar, not an Account object.

A self/forward target uses a deferred column supplier:

```python
class NewAccount(Record):
    # Other fields omitted here; see the runnable application tour.
    manager_id: ForeignField[Account, AccountId | None] = foreign(
        lambda: Account.id, default=None, on_update="CASCADE"
    )
```

Python 3.14's `annotationlib.Format.FORWARDREF` lets declaration processing inspect
logical value types without resolving the future read-class target prematurely.
`foreign_keys(ReadClass)` resolves targets, checks logical domains and contradictory
target annotations, and emits FK fragments. Source fields in composite metadata
bind to the read class, not to the input class that holds their declarations.
Composite arity, domain, ownership and exact column pairing are runtime checks;
this metadata constructor does not promise a static domain/arity proof.

This intentionally accepts the repeated target fact in `ForeignField[Account, T]`
and `foreign(Account.id)` in exchange for declaration locality and target-aware
joins. The earlier independent-relationship variant remains executable research,
but is no longer the preferred application spelling.

### Column-explicit joins and nullable roles

```python
select(Entry, Account).join(Account, on=Entry.account_id.references(Account.id)).all()

select(employees.column(Account.name), managers.column(Account.name)).join(
    managers,
    on=employees.column(Account.manager_id).references(managers.column(Account.id)),
).all()

notes = outer(Entry, NoteRole, name="notes")
select(Account.name, notes.column(Entry.note)).left_join(
    notes, on=notes.column(Entry.account_id).references(Account.id)
).all()
```

The alias column retains original model identity, declared FK target, logical
value, and SQL role separately. Wrong target models and incompatible value domains
are rejected statically. A different same-typed column on the correct target model
can still pass ty; runtime binding rejects it against the declaration.

Composite joins name their comparisons explicitly, for example:

```python
on = Entry.tenant_id.eq_col(Account.tenant_id) & Entry.account_id.references(Account.id)
```

An explicit predicate is not a proof that every component of a declared composite
FK was included. The physical composite constraint separately enforces same-row
membership, with SQLite's usual NULL behavior.

Nullable and ordinary roles remain distinct. Replacing `notes.column(Entry.note)`
with `Entry.note`, or a nonnullable alias, fails typing at consumption. Optional
whole rows use `notes.row(present=Entry.id)`. A nullable role cannot supply FROM by
itself; select the root model, join, then project the optional field.

The revision exposed an inference hole in nullable alias comparisons: an overloaded
comparison could infer `Unknown`, accepting an unjoined predicate operand. A
read-only covariant value witness now handles nullable lifting. Source scopes and
FK target models remain invariant. Exact predicate-type assertions and challenge
cases for unjoined operands cover both `.eq_col` and `.references`.

### Transactions and RETURNING

```python
async with Transaction(connection) as transaction:
    rows = await transaction.fetch_all(select(Account).all())
    account = await transaction.fetch_one(select(Account).where(Account.id.eq(key)))
    missing = await transaction.fetch_one_or_none(
        select(Account).where(Account.code.eq("MISSING"))
    )
    inserted = await transaction.execute(
        insert(Account.create(code="A", name="Ada")).returning()
    )
    changed = await transaction.execute(
        update(Account)
        .set(Account.name.to("Augusta"))
        .where(Account.id.eq(inserted.id))
        .returning()
    )
```

Queries have no public `fetch`; writes have no public `execute`. Transaction
methods reject incomplete plans under ty. The prototype owns BEGIN/COMMIT/ROLLBACK,
checks its active lifetime, rolls back exceptional exits, and shields cleanup from
cancellation. Nested transactions and concurrent use are not implemented.

Like current snekql, INSERT RETURNING produces the fetched model and UPDATE
RETURNING produces a list through `transaction.execute`. Without RETURNING, INSERT
returns None and UPDATE returns the affected-row count. Those paths emit actual
non-returning SQL; they do not fetch and discard models.

The existing experimental conflict-ignore policy remains different from current
snekql: explicit RETURNING can produce `Row | None`. Current snekql rejects
DoNothing with RETURNING at compilation. The companion documents that distinction.

`fetch_one` requires exactly one row. `fetch_one_or_none` permits zero or one and
rejects a materialized scalar None at runtime to avoid ambiguity. Current snekql
is stricter and excludes scalar builder selects for that operation. This prototype
still buffers complete results; it does not add production cardinality pushdown,
streaming, pooling, backend checks, or nested-transaction policy.

Both application tours now execute SQLite `ON UPDATE CASCADE`, including self and
composite FKs. Updating a parent key changes dependent FK values. RETURNING covers
the directly updated table, so examples refetch dependents to observe cascades.
Previously materialized Python objects stay unchanged.

## Guarantees and limits

- An invariant `Occurrence[Scope, Row]` witness anchors joins. A bare class argument
  alone can widen: the retained counterexample inferred
  `Entry | Account | Other` even though only Account was being joined.
- Available sources are invariant; projection requirements are covariant. Fetch,
  terminal mapping, and `Select[Result]` helper returns require all demanded
  sources plus readiness. Conjunctions and comparisons retain both owners.
- Read/input classes remain distinct. Direct predicates also work with existing
  prototype update plans. The revision adds explicit returning/non-returning
  execution without replacing the existing codecs.
- Structural classmethod witnesses also accept **read instances** as sources.
  They query the instance's table and ignore its stored values. This behavior is
  tested and disclosed, not presented as a class-only guarantee. Input instances
  and input classes do not gain those witnesses. A production class-only interface
  would need a separate metaclass/descriptor or source-contract investigation.
- Role classes cannot prove equal runtime SQL names. Reusing one role under two
  names can pass ty and fail compilation. Conversely, distinct roles cannot
  reuse one case-insensitive SQL name. The runtime checks both facts.
- Direct literal alias names retain identity. Broad `LiteralString` parameters
  erase that distinction; those accepted counterexamples fail runtime validation.
- Presence-witness nonnullability is runtime-checked, with the earlier prototype's
  annotation-resolution limits. Filtering does not statically narrow outer slots.
- A tuple logical result and a multi-slot SQL projection are not assumed to have
  identical constructor semantics. Only the tuple-specific selection carrier
  exposes positional `.into`; `.map` always receives the complete result.
- Dynamic callers still face source/readiness/identity checks. Static checking is
  not a proof of candidate keys, schema compatibility, row existence, tenant
  authorization, or business meaning. Ordinary erased column comparisons do not
  gain the relationship factory's runtime domain validation.

This reuses the earlier bounded SQLite engine and curated-codec experiment. It
does not add production schema registration, migrations, backend propagation,
MariaDB execution, correlated queries, CTEs, aggregates, ordering, or pagination.
The methods added to `records.py` and `ReadRow` are prototype bridges. Lazy imports
avoid a declaration/query import cycle; production layering is not settled here.

## Evidence and reproduction

```sh
bash scratchpad/dual_queries/run.sh
uv run ty check
```

- **158 isolated typing observations**, each with a clean positive control and
  diagnostics restricted to the challenge. Exact inferred types cover the main
  result, callback, source, and alias claims.
- **85 expected diagnostics**: 80 rejection cases and five unsupported/interface
  limitation cases. A rejection is not automatically a desirable guarantee.
- **73 accepted observations**: 57 capabilities and 16 accepted counterexamples
  or behaviors that cannot be claimed as exclusions.
- **53 runtime tests in this directory**, covering actual SQLite selection, projection, aliases,
  nullable rows, constructor mapping, relationships, deferred execution, dynamic
  guards, class-local FK metadata, SQLite cascades, transaction ownership, write
  RETURNING contracts, rollback, cardinality, and the competing callback capture.
- The runner also reruns the earlier **91 typing observations and 41 runtime
  tests**, plus the updated, original-explicit, and current-snekql application tours.
- **1,077 existing fast tests passed** with `PYTHON_CONTEXT_AWARE_WARNINGS=1`.
  Full-repository ty, Ruff lint, formatting, and diff checks passed. No complete
  integration/database suite or MariaDB server run.

The failed internal loop experiment triggered a ty cycle-iteration panic while
repeatedly assigning a growing variadic query back to one variable. Constructing
the stored projection tuple directly avoids it. A checker crash was never counted
as a successful rejection. `variadic_loop.py.txt` preserves a minimal manual
reproducer and the passing direct-construction control. No crash remains in the
retained executable modules.

Read `interface.py`, `relationships.py`, `execution.py`, and `writes.py` for the
implemented query, relationship, transaction, and write contracts; `options.pyi` for static-only
competitors, `cases.json` and `results.json` for caller evidence, and the focused
`test_*.py` files for runtime claims. Constructors and internal data carriers are
research machinery, not hardened public extension points.
