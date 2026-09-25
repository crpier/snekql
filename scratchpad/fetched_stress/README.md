# Fetched-first nesting under larger contracts

Local, uncommitted research on `research/fetched-first-stress`, based on main
`56dbc32`. Related [research issue #396](https://github.com/crpier/snekql/issues/396)
remains closed. No production edits, publication, dependency changes, or checker
plugins. The class-body result alternative remains independent.

## Verdict

The explicit-link nested design survives these tests. Complete rows retain the
short name, own storage, and remain the SQL sources. Nested Pending values have
independent constructors and infer the complete row from implicit INSERT.

The earlier adapter was not sufficient unchanged. Self-referential annotations
exposed premature pairing checks. MariaDB needed its own namespace and Column
Type constructors. This study extends the adapter in this directory rather than
rewriting the prior evidence.

The strongest remaining costs are visible in application code:

- The 20-field Order repeats **20 input field annotations**, although it declares
  storage only once. Cross-class drift is partly a runtime declaration check.
- Methods do not become shared merely because the classes are nested. Shared
  behavior needs free functions, delegation, or a suitable data-free mixin.
- Cyclic FKs require deferred targets and deferred target-agreement checks.
  Nesting does not remove graph-resolution requirements.

I still favor this as the dual-class candidate. Original lifecycle generics remain
more economical when single field declarations and naturally shared methods
matter most.

## Review in four parts

1. [large.py](large.py), [test_large.py](test_large.py), and
   [native_models.py](native_models.py): the 20-field Order versus original snekql.
2. [cycles.py](cycles.py), [test_cycles.py](test_cycles.py), and
   [test_guards.py](test_guards.py): self/mutual references and binding failures.
3. [methods.py](methods.py), [test_methods.py](test_methods.py): behavior shared
   without incomplete-is-complete inheritance.
4. [maria_models.py](maria_models.py), [maria_cycles.py](maria_cycles.py), and
   [test_mariadb.py](test_mariadb.py): native MariaDB fields and actual execution.

Adapter implementation is in [contracts.py](contracts.py), [sqlite.py](sqlite.py),
and [mariadb.py](mariadb.py). It reuses earlier storage capture, native validation,
codecs, graph finalization, query compilation, and transaction adapters. It is not
a production extraction or a new storage engine.

```sh
bash scratchpad/fetched_stress/run.sh
uv run python -m scratchpad.fetched_stress.tour
```

The full runner starts a disposable MariaDB server using existing test support.
The tour uses an in-memory SQLite database. Research transaction adapters translate
commands only; the native runtime owns connections and transactions. Native
UPDATE/DELETE bridges in selected constraint tests are identified explicitly.
They do not establish a new typed nested-model UPDATE/DELETE interface.

## Larger models

Order has generated identity, generated timestamp and revision, nominal tenant
and order IDs, status/currency Literals, three canonical Decimal values, UUID,
BLOB bytes, structured JSON-in-Text, Boolean, ordinary integers, and nullable
text/integer/datetime fields.

Its application usage stays compact despite the longer declaration:

```python
pending = sample_order()  # Order.Pending
order = await transaction.execute(sqlite.insert(pending).returning())  # Order
orders = await transaction.fetch_all(sqlite.select(Order).all())  # list[Order]
```

The tests check exact generated and ordinary field types, constructor keywords,
nominal-ID misuse, invalid Literals, JSON value types, model/scalar results, and
runtime materialization. The row constructor still requires fields that Pending
can default or omit. A Pending instance is not accepted where Order is required.

The original NativeOrder declares the same 20 storage fields once. Its Scaffold
matches the nested model byte for byte. It executes the same monetary calculation
and materializes `NativeOrder[Fetched]`. This confirms native codecs and storage
are doing the work; those capabilities are not benefits unique to nesting.

The original fetched-constructor sentinel hole remains an executable control.
The nested row's stricter constructor is useful, but it still proves neither
current database existence nor fetched provenance.

Both naming clarity and repetition become more pronounced at this size. I would
not hide the repetition behind a runtime decorator that the checker cannot see.
Generation could be a separate option, not a requirement of this declaration.

## Self and mutual foreign keys

The tested shape keeps references field-local:

```python
class Node(sqlite.Row):
    table_name = "nodes"
    node_id: sqlite.Field[int] = sqlite.Integer(primary_key=True)
    parent_id: sqlite.ForeignField[Node, int | None] = sqlite.ForeignKey(
        lambda: Node.node_id, on_update="CASCADE", on_delete="SET NULL"
    )
    name: sqlite.Field[str] = sqlite.Text()

    class Pending(sqlite.Pending):
        __row__: ClassVar[type[Node]]
        node_id: sqlite.Field[int]
        parent_id: sqlite.ForeignField[Node, int | None] = sqlite.default(None)
        name: sqlite.Field[str]
```

Department.manager_id references Employee.employee_id through a callback.
Employee.department_id references Department.department_id directly. Both Pending
classes repeat the target and value annotations. The outward `__row__` remains
an ordinary, unquoted class-body annotation.

Observed behavior:

- Module-level and function-local self references bind.
- A Pending value can be constructed before a mutually referenced class exists.
- Function-local mutual declarations bind after both classes exist.
- SQLite executes mutual joins, self-FK and mutual-FK cascades, SET NULL on delete,
  and missing-parent rejection.
- MariaDB executes self references and a mutual-FK cascade after a reviewed cyclic
  migration.
- Rootless **storage derivation** cycles reject. A cyclic table graph with concrete
  integer roots is a different case and works.
- Premature schema use fails and remains failed after the missing class arrives.
  The inherited once-binding policy memoizes failures; construction alone does
  not trigger that binding.

### Why the adapter changed

The earlier nested adapter compared unresolved outer and inner target annotations
at outer-class completion. The self-reference test failed with
`Input override must preserve field kind, target and value type`.

The new adapter checks field sets, descriptor kinds, logical types, defaults, and
the outward row witness during declaration. It checks each foreign target's
**resolved class identity** against both contracts at graph binding. It also
compares logical domains, allowing local nullability without conflating it with
omission. Wrong owner and wrong value-domain declarations can still pass ty, but
schema binding rejects them.

The old FK constructor's invariant value parameter also rejected a nullable local
reference to a non-null target ID. The extension lets the field annotation supply
local nullability. Its constructor returns a target-aware descriptor with an
internal Any value coordinate, like the broad Column Type constructor convention.
Consequently, constructor-level value-domain disagreement is checked at runtime,
not proven statically. Declared fields, joins, and query results retain exact types.
This is a tested compromise, not a claim that no stronger constructor is possible.

The earlier failure is retained in [test_legacy.py](test_legacy.py), with a separate
static challenge for the nullable constructor. The original native self-FK control
works. The tested native mutual FKCol forward-annotation spelling rejects its
first declaration. That does not establish that all native representations of
cyclic constraints are impossible.

### MariaDB cycles still need migration work

CREATE-only Scaffold fails for the tested mutually dependent MariaDB tables.
The working test uses authored CREATE statements followed by ALTER ADD FOREIGN
KEY, verifies the resulting schema, and executes the cascade. Foreign-key checks
stay enabled. Nesting is not migration planning.

## Shared methods

The smallest reusable behavior accepts a read-only structural contract:

```python
class Amounts(Protocol):
    @property
    def subtotal(self) -> Decimal: ...

    @property
    def tax(self) -> Decimal: ...

    @property
    def discount(self) -> Decimal: ...


def invoice_total(order: Amounts) -> Decimal:
    return order.subtotal + order.tax - order.discount
```

Both Order and Order.Pending satisfy it because those monetary fields are always
available. A protocol requiring the generated order_id rejects Pending.

For method syntax, the tested data-free mixin uses an explicit self contract:

```python
class Totals:
    def total(self: Amounts) -> Decimal:
        return invoice_total(self)
```

Order inherits `Totals, sqlite.Row`; its nested Pending inherits
`Totals, sqlite.Pending`. Both `.total()` calls type-check and execute.
`Totals().total()` is rejected because Totals alone does not supply the fields.

Order.receipt_key needs its generated identity, so it lives only on Order.
Pending neither inherits it nor becomes an Order subtype. Assignments remain
frozen, but nested dictionaries remain mutable. Frozen fields are not deep
immutability.

Directly inheriting a Protocol as the model mixin conflicts with the research
metaclass. Keep the Protocol as an annotation and the data-free mixin as an
ordinary class. Arbitrary mixins with constructor hooks, storage declarations, or
metaclasses are outside this evidence.

Concrete row inheritance initially exposed another adapter hole: a subclass could
silently lose inherited storage from its private schema. The new adapter rejects
that pattern rather than pretending it supports model inheritance. Pure behavior
mixins remain supported. An inheritance redesign needs its own study.

My preference is the protocol/free-function form for reusable domain calculations.
Use the mixin when method syntax earns the added inheritance. Original generics
still make sharing methods easier because there is only one value class.

## MariaDB-specific fields

Product owns native Decimal(12,2), bounded/collated Text, Uuid, DateTime with server
CurrentTimestamp, Json, Boolean, LongText, Blob, and generated Integer storage.
It also declares a LongText prefix index. Pending repeats logical/descriptor
annotations and input default choices, not storage options.

Specialized JSON annotation remains explicit on both contracts:

```python
# Complete Product:
payload: mariadb.JsonField[dict[str, int]] = mariadb.Json()

# Product.Pending:
payload: mariadb.JsonField[dict[str, int]]
```

That preserves the class-level operator:

```python
answers = await transaction.fetch_all(
    mariadb.select(Product.payload.json_extract_int("$.answer")).all()
)
# list[int | None]
```

Actual MariaDB tests verify INSERT RETURNING, SELECT materialization, Decimal,
UUID, UTC millisecond datetime, generated datetime, JSON extraction/missing paths,
Boolean, BLOB, LongText, and a Decimal-valued FK join/cascade. Schema verification
runs on the seeded Product/PriceReference graph and reviewed cyclic graph.
The native Product control has identical Scaffold and executes its own JSON query.

The existing finalizer preserves Decimal precision when deriving FK storage.
A native control still reproduces the missing-precision metadata error. That
adapter repair predates nesting and must not be credited to the nested design.

Switching JsonField to plain Field in Pending is statically accepted but rejected
at declaration. A plain Field does not gain JSON operators just because its
runtime storage is JSON. Backend-mismatched input declarations likewise need a
runtime guard in addition to query-family typing.

## Evidence and limits

- **73 independent typing observations:** 28 capabilities, 32 rejections,
  11 accepted counterexamples, two unsupported contracts.
- **50 runtime tests**, including **12 actual MariaDB tests** and native controls.
- **1,127 existing fast tests** passed in 24.33 seconds.
- Prior nesting: **48 observations / 29 tests**.
- Prior finalization: **33 observations / 31 tests**, including MariaDB.
- Prior backend namespaces: **54 observations / 22 tests**, including MariaDB.
- Repository ty, Ruff lint/format, and tracked diff checks passed.

[cases.json](cases.json) and [results.json](results.json) record independent clean
controls, challenge-line diagnostics, checker versions, and source hashes.
[evidence.json](evidence.json) records consumer lint, 20/20 authored field counts,
matching Scaffold, and MariaDB 12.3.2. Useful failures and validation logs live
under `.git/fetched-first-stress/`.

The five nested consumer modules need neither future imports, quoted result bases,
nor import exceptions. Deferred FK callbacks remain necessary where names are not
yet available. The study does not remove every forward reference.

No alias/self-join study, arbitrary inheritance, full query/backend parity,
framework integration, client default-factory expansion, performance benchmark,
or production concurrency claim. This study is large enough to expose repetition
and resolution problems, not to establish an application-size limit.

The result supports continuing with explicit-link fetched-first nesting. It also
makes the implementation obligations clearer: truthful independent constructors,
checked descriptor/default agreement, deferred FK graph binding, backend-specific
field operators, and an explicit policy for unsupported inheritance.
