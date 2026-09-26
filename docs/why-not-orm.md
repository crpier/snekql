# Why snekql is not an ORM

If you want to write queries without having a session track your Python objects,
snekql may fit. A model describes columns and values. It does not decide when to
load related rows or save changes.

This keeps database work visible in your code, but leaves more decisions to you:
you write the joins, updates, migrations, and transaction boundaries.

## The boundary

Creating a model value does not connect it to a database. You explicitly insert
it through a transaction:

```python
user = User(email="alice@example.com")
await tx.execute(insert(user))
```

After insertion, `user` remains the same immutable pending value object. snekql
does not attach it to a runtime, mark it clean/dirty, or persist future
mutations.

To read database-filled values, either issue a select, or ask the write itself
to return the row the database produced with `.returning()`:

```python
fetched_user = await tx.fetch_one(
    select(User).where(User.email.eq("alice@example.com")),
)

# Or recover generated values (auto-increment keys, server defaults) directly
# from the write, with no follow-up select:
fetched_user = await tx.execute(insert(user).returning())
```

`.returning()` is the write-side bridge from a Pending model to a Row one;
it is always explicit, so a plain `insert(...)` still returns `None`.

## Bulk inserts

Use `insert_many(User, rows)` to write a Pending batch to its declared table.
`.returning()` yields a list of `User[Row]`, including a typed empty list for an
empty batch:

```python
from snekql.sqlite import insert_many

await tx.execute(
    insert_many(User, [User(email="a@example.com"), User(email="b@example.com")])
)

created = await tx.execute(
    insert_many(
        User, [User(email="c@example.com"), User(email="d@example.com")]
    ).returning(),
)
```

Every row must belong to the destination model and supply the same columns for
one `VALUES` list. Empty batches execute no SQL but retain their backend, so
executing them through the wrong backend still raises an error. `insert(user)`
accepts one Pending value, never a sequence.

## What snekql avoids

snekql does not include:

- identity maps;
- lazy relationship loading;
- relationship configuration;
- session/unit-of-work APIs;
- dirty tracking;
- automatic persistence of object mutations;
- implicit SQL generated from attribute access.

## Why this matters

Explicit SQL-shaped operations make the cost and scope of database work visible.
For example, a full-table update must be spelled as `.all()`:

```python
await tx.execute(update(User).set(User.status.to("inactive")).all())
```

A filtered update must be spelled as `.where(...)`:

```python
await tx.execute(
    update(User)
    .set(User.status.to("inactive"))
    .where(User.email.eq("alice@example.com")),
)
```

If neither intent is chosen, compilation/execution fails before SQLite sees the
query.

## When to choose something else

Use an ORM if tracked objects and relationship loading are central to how you
want to write the application. Use raw SQL directly if you do not want model
and query declarations. snekql is for the middle case: explicit database work
with Python validation and checked result types.

[Try it](getting-started.md) · [All guides](README.md)
