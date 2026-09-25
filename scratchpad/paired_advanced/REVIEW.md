# What to compare

Start with body.py and dual.py, sections 14, 22, 24, and 28. Those cover optional
model pairs, recursive referral traversal, typed writes, and streaming. The same
operations occur in the same order in both files.

## Model results differ more than the query algorithms

These are the actual function annotations:

```python
# Class-body
async def optional_posts(
    transaction: Transaction,
) -> list[tuple[User[Fetched], Post[Fetched] | None]]: ...


# Dual
async def optional_posts(
    transaction: Transaction,
) -> list[tuple[UserRow, PostRow | None]]: ...
```

Both materialize complete author/post pairs, with None for the missing post.
The earlier dual adapter returned only the root model. This bridge now matches
native join semantics instead of treating the older limitation as a design cost.

## Typed writes are equally direct after column integration

The runnable bodies are:

```python
# Class-body
return await transaction.execute(
    sqlite.update(User)
    .set(User.balance.to_expr(User.balance.add(amount)))
    .where(User.user_id.eq(identity))
    .returning()
)

# Dual, with its required experimental conversion visible
balance = column(UserRow.balance)
user_id = column(UserRow.user_id)
users = table(UserRow)
return await transaction.execute(
    sqlite.update(users)
    .set(balance.to_expr(balance.add(amount)))
    .where(user_id.eq(identity))
    .returning()
)
```

The result is list[User[Fetched]] versus list[UserRow]. Both reject tested wrong
assignment domains and owners. The SQL and ordered parameters match. The explicit
conversion is not desirable final syntax, but removing it requires real descriptor
integration, not merely renaming functions.

## Shared value helpers still show the clearest difference

```python
# Dual, one class includes both value forms.
def label(user: User) -> str:
    return user.nickname or user.email


# Class-body, bare User defaults to Pending.
def label(user: User[Pending] | User[Fetched]) -> str:
    return user.nickname or user.email
```

The dual class method also uses ordinary self. The body method names the lifecycle
union. Both have a precise generated-ID-dependent method, available only on the
complete form.

For generic helpers, direct body descriptor access still fails even with a
union-bound type variable. helpers.py demonstrates a working body alternative
using a read-only Contact protocol for access while retaining the precise return
type. There is a workaround; it costs more annotation machinery.

## Two decisions remain

1. **Should complete rows satisfy input-accepting functions?** Dual deliberately
   says yes. That simplifies common helpers and allows inserting a complete value.
   Body keeps the lifecycle types separate and rejects fetched insertion. Neither
   interpretation means that a manually completed value exists in the database.
2. **Where should declaration complexity live?** Body keeps one field declaration
   but carries Pending/Fetched into value annotations and some methods. Dual
   carries an extra row declaration and generated-field refinements, but complete
   values and input-compatible behavior use ordinary Python classes.

Advanced SQL did not reveal a new reason to choose either answer. Practical
adoption still favors body because its query runtime is already integrated.
That is different from preferring its long-term application interface.

Direct fetched construction remains a minor consideration. It should not outweigh
query safety, shared behavior, or the insertion policy.
