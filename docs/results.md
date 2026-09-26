# Give query results names

Tuples work well for a few columns. When a result needs names, return a Pydantic
model instead. This is an output shape, not another table declaration.

These examples use the `User` with `id` and `email` from
[getting started](getting-started.md).

## Named projections

Use a plain Pydantic `BaseModel` as a result model when positional tuples are
awkward or a query needs more than eight projected values. It is not a table
model and declares no storage, primary key, or schema.

```python
from pydantic import BaseModel
from snekql.sqlite import ClosedRead, Transaction, ready, select


class UserSummary(BaseModel):
    id: int
    email: str


def summaries() -> ClosedRead[UserSummary]:
    return ready(
        select(User).project(
            UserSummary,
            id=User.id,
            email=User.email,
        )
    )


async def load_summaries(transaction: Transaction) -> list[UserSummary]:
    return await transaction.fetch_all(summaries())
```

Each keyword names a result field. Its value says which column or expression
fills that field. You can use columns, aggregates, scalar subqueries, or supported
SQL expressions. Field names, not keyword order, determine where values go.

Named results do not have the eight-field limit of positional projections.
Database limits still apply.

## Joins and missing values

Build joins before calling `.project(...)`. Fields from the nullable side of a
LEFT JOIN must accept `None`, including alias columns whose physical storage is
NOT NULL. Filters do not refine that declared nullability. Named queries retain
`where`, `all`, `order_by`, `group_by`, `having`, `distinct`, `limit`, and `offset`.
They work with eager fetches and `fetch_chunks`. A named row containing a NULL
field remains distinguishable from no row in `fetch_one_or_none`.

## What is checked

Every declared result field needs exactly one binding, including fields with
Python defaults. Extra or missing bindings and labels differing only by case
are rejected. Labels are quoted SQL identifiers and use Python field names,
not Pydantic validation/serialization aliases. Table models and `RootModel`
are not named result models. A one-field named row is still a row object;
use a scalar select, not a named projection, for a scalar subquery.

Construction checks compatible known value types and whether a field can be
NULL. On a read, snekql decodes UUIDs, JSON, dates, and other values before
Pydantic validates the result model strictly. Constraints and types that cannot
be decided while building the query are checked against the actual rows.
`validate=False` can skip source-column validators, but never named result
validation. Invalid result rows raise `ModelValidationError` without including
Pydantic input values or validator messages.

## Named RETURNING results

Use `.returning_as(Result, **bindings)` on supported writes:

```python
query = sqlite.insert(User(email="ada@example.com")).returning_as(
    UserSummary,
    id=User.id,
    email=User.email,
)

# created = await tx.execute(query)  # UserSummary
```

Bindings must be columns of the written model. Named RETURNING has the same
validation and arity rules as named SELECT. A single insert returns one result
object. Bulk inserts and SQLite UPDATE/DELETE return lists. Empty bulk inserts
remain no-ops returning `[]`. Existing `DoUpdate` conflict actions work;
`DoNothing` still cannot be combined with RETURNING.

SQLite supports named INSERT, UPDATE, and DELETE RETURNING. MariaDB supports
named INSERT RETURNING; this library still rejects MariaDB UPDATE/DELETE
RETURNING before IO. On UPDATE/DELETE, a later `.returning(...)` replaces the
named contract with the usual scalar, tuple, or whole-model result.

A result model does not grant database permissions or make an internal field safe
to expose. Choose which fields belong in an HTTP response separately.

Next: [CTEs](ctes.md), [UNION](unions.md), or [result typing](typing.md#query-result-shapes).
[All guides](README.md)
