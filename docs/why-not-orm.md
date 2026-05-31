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

To read database-filled values, issue a select:

```python
fetched_user = await tx.fetch_one(
    select(User).where(User.email.eq("alice@example.com")),
)
```

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
- Use **Fetched Model** for rows materialized by the runtime.

See `CONTEXT.md` for the project language glossary.
