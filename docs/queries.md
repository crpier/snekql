# Read and write data

A query describes work. A transaction runs it. You can build a query, pass it to
another function, or [inspect its SQL](inspecting-queries.md) without opening a
connection.

These examples use the `User` model from [the model guide](models.md), with
`id`, `email`, and `status` columns. Imports come from `snekql.sqlite`; use the
MariaDB namespace for MariaDB models and transactions.

## Choose what comes back

```python
from snekql import sqlite

users = sqlite.select(User)
emails = sqlite.select(User.email)
contacts = sqlite.select(User.id, User.email)
```

Passed to `tx.fetch_all`, these produce:

| Query | Result |
| --- | --- |
| `select(User)` | `list[User[sqlite.Row]]` |
| `select(User.email)` | `list[str]` |
| `select(User.id, User.email)` | `list[tuple[int, str]]` |

A single selected column gives you values, not one-item tuples. For results
with named fields, use a [Pydantic result model](results.md).

## Filter, sort, and limit

```python
query = (
    sqlite.select(User)
    .where(User.status.eq("active"))
    .order_by(User.email.asc())
    .limit(20)
)
```

A SELECT is executable as soon as you build it. Add `.where(...)` to filter
rows, or use the unfiltered query directly. Ordering and limits need no separate
acknowledgment. SELECT has no `.all()` method. When migrating older code,
delete SELECT `.all()` calls; do not replace them with another call.

UPDATE and DELETE still require `.where(...)` or an explicit `.all()`. UPDATE
also needs `.set(...)`.

Use column methods rather than Python comparison operators:

| SQL intent | Python |
| --- | --- |
| Equal / not equal | `.eq(value)` / `.ne(value)` |
| Greater / less than | `.gt(value)` / `.lt(value)` |
| Inclusive bounds | `.gte(value)` / `.lte(value)` |
| Within a range | `.between(low, high)` |
| In a set | `.in_(values)` |
| Text pattern | `.like(pattern)` |
| SQL NULL | `.is_null()` |

Combine conditions with `&`, `|`, and `~`, not Python's `and`, `or`, or `not`:

```python
query = sqlite.select(User).where(
    User.status.eq("active")
    & (User.email.like("%@example.com") | User.email.like("%@example.org")),
)
```

Each extra `.where(...)` adds an AND condition. Query objects are immutable;
keep the returned object when you add a filter or another clause.

## Pick a fetch method

Run these inside `async with db.transaction() as tx:`:

```python
users = await tx.fetch_all(sqlite.select(User))
user = await tx.fetch_one(sqlite.select(User).where(User.id.eq(7)))
maybe_user = await tx.fetch_one_or_none(
    sqlite.select(User).where(User.id.eq(7)),
)
```

- `fetch_all` returns a list, possibly empty.
- `fetch_one` requires exactly one row. It raises `NoResultError` for zero and
  `MultipleResultsError` for more than one.
- `fetch_one_or_none` allows zero or one whole row. More than one is still an error.

Cardinality applies to the result after SQL filtering, limits, and offsets.
`fetch_one(query)` detects multiple results; `fetch_one(query.limit(1))` deliberately
chooses at most one and cannot detect duplicates. A limit does not create a row.
Use an explicit ordering with a tie-breaker when choosing the first row matters.
`fetch_all(query.limit(1))` still returns a list.

A nullable scalar can itself be `None`, so it cannot unambiguously mean “no
row.” Use a model, tuple, or [named result](results.md) when you need to distinguish
an absent row from a NULL field.

For large result sets, [stream batches](transactions.md#stream-large-results)
instead of loading everything with `fetch_all`.

## Insert one row or a batch

```python
one = sqlite.insert(User(email="ada@example.com"))
batch = sqlite.insert_many(
    User,
    [User(email="grace@example.com"), User(email="linus@example.com")],
)
```

Run them with `await tx.execute(one)` and `await tx.execute(batch)`.
Without RETURNING, inserts return `None`.

`insert` takes one Pending value. `insert_many` takes the destination model and
a sequence of its Pending values. Every row must supply the same columns for
one SQL VALUES list. An empty batch runs no SQL but still belongs to that model's
backend. Rows from SELECT or `complete` cannot be inserted.

To get generated values back:

```python
created = await tx.execute(
    sqlite.insert(User(email="ada@example.com")).returning(),
)
# created: User[sqlite.Row]
```

A batch with `.returning()` returns a list. Both backends support INSERT RETURNING.
See [result shapes](results.md#named-returning-results) for selecting specific
columns or a named result.

## Update or delete

```python
change = (
    sqlite.update(User)
    .set(User.status.to("disabled"))
    .where(
        User.id.eq(7),
    )
)
remove = sqlite.delete(User).where(User.status.eq("disabled"))
```

`await tx.execute(change)` and `await tx.execute(remove)` return an affected-row
count. SQLite UPDATE counts matched rows; MariaDB UPDATE counts rows that
actually changed. Do not assume the counts mean the same thing.

Use `.all()` deliberately for a full-table write:

```python
change_every_user = sqlite.update(User).set(User.status.to("inactive")).all()
```

SQLite supports UPDATE and DELETE RETURNING. snekql rejects those operations on
MariaDB. [Backend support](backend-capabilities.md) lists the other differences.

## Handle a unique-key conflict

The model guide declares `User.email` unique. This insert reactivates the existing
user if the email already exists:

```python
query = sqlite.insert(User(email="ada@example.com")).on_conflict(
    User.email,
    action=sqlite.DoUpdate(User.status.to("active")),
)
```

Use `.to_inserted()` to take a column's value from the attempted insert instead
of a fixed value. Use `action=sqlite.DoNothing` to leave the existing row alone.
`DoNothing` cannot be combined with RETURNING, because there may be no returned
row. `DoUpdate` supports RETURNING for one row or a batch.

SQLite targets the specified unique key. MariaDB checks **all** unique indexes
and primary keys; passing a target does not narrow its conflict detection.

## Build larger queries

- [Join tables, use aliases, and write subqueries](joins.md).
- [Calculate values and make atomic updates](expressions.md).
- [Return named fields rather than tuples](results.md).
- [Name a subquery with a CTE](ctes.md), [combine results with UNION](unions.md),
  or [walk a hierarchy with recursion](recursive-ctes.md).
- [Write raw SQL](raw-sql.md) for queries the builder does not express.

When returning queries from helper functions, preserve their source types or
explicitly close them with `ready`. See [read helper annotations](typing.md#read-helper-boundaries).

Next: [transactions](transactions.md). [All guides](README.md)
