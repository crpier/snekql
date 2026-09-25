# Why snekql is not an ORM

snekql intentionally gives applications an explicit query layer rather than an
object persistence layer.

## The boundary

A snekql table model is a row contract and query-building surface. It is not an
entity tracked by a session.

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

snekql v1 does not include:

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

## Agent guidance

When editing or extending snekql, preserve these terms:

- Use **Table Model**, not entity or ORM model.
- Use **Transaction**, not session.
- Use **Query Runtime**, not persistence layer.
- Use **Pending Model** for application-constructed instances.
- Use **Row Model** for complete values from database results or validated
  `complete` snapshots. Completeness does not prove persistence.

See `CONTEXT.md` for the project language glossary.
