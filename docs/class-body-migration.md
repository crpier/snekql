# Migrate to class-body models

Version 0.8.0 is a breaking change. There are no compatibility aliases for the old model
arity, `Fetched`, result-only `Select`, sequence `insert`, or unchecked
`.construct(...)`.

## Declare the Row result inside the model

Move the old second `Model` argument into a class-body witness and rename
`Fetched` to `Row`:

```python
from typing import ClassVar

from snekql import sqlite


class User[State = sqlite.Pending](sqlite.Model[State]):
    __row_type__: ClassVar[sqlite.ReadType[User[sqlite.Row]]]
    id: sqlite.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=sqlite.PENDING_GENERATION,
    )
    email: sqlite.Col[str] = sqlite.Text()
```

Keep existing storage constructors, `Col`, `GenCol`, `FKCol`, MariaDB `JsonCol`,
constraints, indexes, and codecs. This syntax change does not require changing
stored data or rewriting committed migration SQL.

The witness names this same model in Row state. It supplies whole-model SELECT,
RETURNING, and `complete` results. Scalar, tuple, and named projection results are
unchanged. Runtime checks validate the witness; ty does not reject every malformed
witness. A class-body annotation can refer to its own class, but an eager base
expression cannot. Python 3.14+ defers annotations by default, so
`from __future__ import annotations` is not required. That import selects
stringized annotations instead; existing callers may keep it. Neither mode
defers class bases or other ordinary expressions.

## Separate construction from completeness

`User(email=...)` and `User[sqlite.Pending](email=...)` create Pending values.
`User[sqlite.Row](...)` is rejected statically and at runtime. Do not replace old
unchecked construction with a cast. Use a validated snapshot instead:

```python
snapshot = sqlite.complete(User, id=7, email="ada@example.com")
# snapshot: User[sqlite.Row]
```

Supply every declared field, including fields with defaults. `complete` validates
logical Python values, rejects missing/extra fields and generation markers, and
performs no database I/O or storage decoding. Its keyword schema is runtime-checked.
A Row value does not prove that a corresponding database row exists.

`is_complete(value)` tests recorded Row state and narrows only its true branch.
A Pending value stays Pending even when all its generated fields were supplied.
Inserting it does not mutate its state. SELECT and supported RETURNING produce
new Row values. Row values, including snapshots, cannot be inserted.

For instance methods, use explicit `self: User[sqlite.Pending]` or
`self: User[sqlite.Row]`. Shared methods can use a Pending/Row union self type or
an application protocol. Arbitrary state-generic descriptor getters remain
outside the supported typing contract.

## Name batch destinations

Keep `insert(user)` for one Pending value. Replace every `insert(rows)` with:

```python
query = sqlite.insert_many(User, [User(email="ada@example.com")]).returning()
# transaction.execute(query) returns list[User[sqlite.Row]]

empty = sqlite.insert_many(User, []).returning()
# transaction.execute(empty) returns a typed empty list without issuing SQL
```

The destination fixes owner, result type, and backend, including empty batches.
Wrong-model and Row inputs are rejected. Empty batches still reject execution
through the wrong backend and cannot compile to SQL for inspection or EXPLAIN.
Existing conflict handling and supported RETURNING behavior remain available.

## Preserve scope in read helpers

The old `Select[Result]` alias erased table requirements. It is removed. Preserve
scope when a helper accepts an executable query:

```python
async def read_all[Scope, Result](
    transaction: sqlite.Transaction,
    query: sqlite.ReadQuery[Scope, Result],
) -> list[Result]:
    return await transaction.fetch_all(query)
```

For a function returning a result-only query contract, finish composition and
close it explicitly:

```python
def users() -> sqlite.ClosedRead[User[sqlite.Row]]:
    return sqlite.ready(sqlite.select(User).all().order_by(User.id.asc()))
```

`ready` checks the backend and compiles without database I/O. It returns the same
object; it does not repair missing joins or unfinished queries, prove tables
exist, or cache later execution compilation. It is optional for ordinary
transaction execution. Closed annotations expose execution/inspection, not
further query composition.

Use `OptionalRead[Scope, Result]` or `ClosedOptional[Result]` for helpers calling
`fetch_one_or_none`. A nullable scalar result is not an optional-row contract:
SQL NULL and no row would both be `None`. `ready` preserves that distinction.
`ClosedRead[Result]` and `ClosedOptional[Result]` use `Never` for closed scope;
that does not mean an empty SQL FROM clause.

`Write[Result]` remains the executable write annotation.
`PendingInput[Owner, Result]` preserves the owner and whole-model RETURNING type
in a generic insert helper. All these names are annotations, not constructors.

## Review stricter checks and their limits

- Use bare declarations such as `select(User)`, `update(User)`, and `alias(User,
  Role, name="author")`. Model instances and structural lookalikes fail typed
  source checks. Native aliases and CTEs remain valid query sources, not mutation
  targets. Explicit lifecycle-specialized sources such as `User[Row]` still pass
  ty in the tested calls but are rejected at runtime.
- The six column-comparison methods now retain both owners. Join every referenced
  table. Some valid enclosing-table correlations in nested JOIN ON clauses need
  a typing escape because general correlation typing is not modeled. Runtime
  correlation support is preserved.
- Field reassignment is rejected by ty as well as at runtime, in both states.
  Freezing is shallow: nested JSON containers remain mutable. SQL assignments
  through `.to(...)` remain valid, including generated fields where permitted.
- Any/callable erasure can hide type evidence. Witness consistency, snapshot
  keyword validation, some FK domains, named bindings, and SQL validity still
  need runtime checks. Nominal IDs are not authorization, and defaults do not
  establish database ownership of a field.

Only ty is supported for this interface. Pyright and mypy fail required positive
controls; extra errors on invalid examples do not establish support. See
[the checker assessment](typing-compatibility.md) for versions and reproduction.
