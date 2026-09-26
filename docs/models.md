# Define your tables

A model describes one table's columns and the Python values you read or write.
It does not create the table, load related objects, or save attribute changes.

Use the namespace for your database. The examples here use SQLite; MariaDB
models inherit from `mariadb.Model` and use MariaDB column constructors.

## Start with a model

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
    email: sqlite.Col[str] = sqlite.Text(unique=True)
    status: sqlite.Col[str] = sqlite.Text(default="active")
```

Read `email: Col[str] = Text(...)` as “a Python string, stored as database text.”
The annotation controls Python validation. The constructor chooses database
storage and options such as uniqueness. See [choosing storage](storage.md) for
dates, decimals, UUIDs, and JSON.

The default table name is the class name in snake_case. Set
`__tablename__ = "app_users"` inside the class to choose another name.

## Values to insert and values you read

There are two model states:

| State | What it means | Example |
| --- | --- | --- |
| `Pending` | An application-created value you can insert. Generated fields may be missing. | `User(email="ada@example.com")` |
| `Row` | A complete value with every generated field available. | A whole-model SELECT result |

`State = sqlite.Pending` makes normal construction create Pending values.
`__row_type__` tells the checker that a whole-model read returns `User[sqlite.Row]`.
It names the same class, so you only declare the columns once.

A `GenCol[int]` can hold `PENDING_GENERATION` before insertion. On a Row, it is
an `int`. That is why code using a database-generated ID should accept
`User[sqlite.Row]` rather than a bare `User`.

An insert does not change the object you passed in. Ask for the resulting row:

```python
pending = User(email="ada@example.com")
query = sqlite.insert(pending).returning()
# created = await tx.execute(query)  # User[sqlite.Row]
# pending is still User[sqlite.Pending].
```

## Defaults are not all the same

- `default="active"` supplies a Python value when you omit the field.
- `default_factory=...` calls a function to supply a Python value.
- `default=sqlite.PENDING_GENERATION` lets the insert omit a generated field.
- `default=sqlite.CurrentTimestamp` or `sqlite.LiteralDefault(...)` declares a
  supported database default on a `GenCol`.

A generated field can still accept an explicit value. `GenCol` does not mean
“the database forbids applications from writing this column.” Use database
permissions or constraints when you need that restriction.

Allowing NULL and allowing omission are separate choices:

```python
# In a model declaration:
nickname: sqlite.Col[str | None] = sqlite.Text(default=None)
```

Here the type allows `None`, and the default lets callers omit the field.
Without the default, callers must pass a value, which can still be `None`.

## Change rows with SQL, not attribute assignment

Model fields cannot be reassigned after construction. To update the database,
build an UPDATE:

```python
query = (
    sqlite.update(User)
    .set(User.status.to("disabled"))
    .where(
        User.email.eq("ada@example.com"),
    )
)
# await tx.execute(query)
```

This is shallow immutability. A nested JSON dict or list can still be changed
in Python, but that does not save it to the database.

## Make a complete snapshot without a query

Sometimes you already have every value and need a Row object:

```python
snapshot = sqlite.complete(
    User,
    id=7,
    email="ada@example.com",
    status="active",
)
assert sqlite.is_complete(snapshot)
```

`User[sqlite.Row](...)` is not a supported constructor; use `complete` instead.
It validates Python values without connecting to a database. Supply
**every field**, including fields with defaults. Missing fields, extra fields,
and unavailable generated values are rejected at runtime.

A Row does not prove that a matching database row exists. Snapshots cannot be
inserted, just as query-returned Rows cannot. `is_complete` checks the recorded
state; it does not check the database or guess from the fields you supplied.

## Methods that need a generated value

Put the state on `self` when a method needs it. For example, inside `User`:

```python
def cache_key(self: User[sqlite.Row]) -> str:
    return f"user:{self.id}"
```

Use a Pending/Row union for a shared method when it only needs fields available
in both states. See [method typing](typing.md#instance-methods-and-self) for the
supported forms and limits.

## Constraints and related tables

Use `unique=True`, `index=True`, or a table-level `Index` to declare indexes.
Use `ForeignKey` or `ForeignKeyConstraint` to declare database relationships.
These do not add relationship-loading attributes or make joins implicit.

The detailed declarations are in the [typing and declaration reference](typing.md),
including composite keys, check constraints, callable self references, and
backend-specific indexes. Schema changes still need [migration SQL](migrations.md).

Next: [write queries](queries.md) or [choose storage types](storage.md).
[All guides](README.md)
