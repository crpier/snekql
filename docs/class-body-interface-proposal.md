# Class-body interface proposal

This is the design record behind the class-body interface shipped in 0.8.0.
It is not the getting-started guide. Use [models](models.md) for new code or the
[0.8 migration guide](class-body-migration.md) when upgrading. Progress notes
below describe the work at the time they were written.

The chosen names are `__row_type__` and `Row`. `ReadType` remains the annotation helper. `ready`, `complete`, and `is_complete` keep their proposed names.

## Declare a model once

```python
from typing import ClassVar, NewType, assert_type

from snekql import sqlite

UserId = NewType("UserId", int)


class User[State = sqlite.Pending](sqlite.Model[State]):
    __row_type__: ClassVar[sqlite.ReadType[User[sqlite.Row]]]
    __tablename__ = "users"

    user_id: sqlite.GenCol[UserId] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=sqlite.PENDING_GENERATION,
    )
    email: sqlite.Col[str] = sqlite.Text(unique=True)
    nickname: sqlite.Col[str | None] = sqlite.Text(default=None)

    def label(self: User[sqlite.Pending] | User[sqlite.Row]) -> str:
        return self.nickname or self.email


class Post[State = sqlite.Pending](sqlite.Model[State]):
    __row_type__: ClassVar[sqlite.ReadType[Post[sqlite.Row]]]
    __tablename__ = "posts"

    post_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    author_id: sqlite.FKCol[User, UserId] = sqlite.ForeignKey(User.user_id)
    title: sqlite.Col[str] = sqlite.Text()
```

There is one `User` class, with two states:

- `User[Pending]` is input for an insert. Database-generated values may be missing.
- `User[Row]` has all its values, including database-generated ones.

`User(...)` creates a pending user. Bare `User` in an instance annotation also means `User[Pending]`, not either state. The `label` method explicitly accepts both states so it works before and after insertion.

Keep the existing column declarations and constructors. MariaDB uses the same declaration pattern with its own Column Types and `JsonCol`.

### What does `__row_type__` declare?

This line says, "When an operation returns a whole user, its type is `User[Row]`."

```python
__row_type__: ClassVar[sqlite.ReadType[User[sqlite.Row]]]
```

That includes selecting `User` and returning a whole user from an insert, update, or delete. It also tells the proposed `complete(User, ...)` helper what type to return.

It does not describe every result of a query involving User. Selecting `User.email` still returns strings. Selecting several columns returns tuples. A named projection returns its declared result type.

The declaration gives the type checker an explicit connection between `User` and `User[Row]`. The tested design uses this instead of the old second parameter on `Model`. `ClassVar` keeps it out of the model's fields. The `ReadType[...]` helper lets the library expose that connection to typed query functions. Application code does not instantiate or call it.

`__row_type__` describes the whole-model result, not every possible query result. The double underscores identify library metadata, like `__tablename__`; Python gives this name no special meaning.

`Row` replaces the old name `Fetched`. There is no extra class or conversion. The name also fits values made with `complete`, which have all their fields without having come from a database.

## Insert and select normally

```python
async def register(database: sqlite.Database, email: str) -> User[sqlite.Row]:
    async with database.transaction() as transaction:
        row = await transaction.execute(sqlite.insert(User(email=email)).returning())
        assert_type(row, User[sqlite.Row])
    return row


async def author_posts(
    transaction: sqlite.Transaction,
) -> list[tuple[User[sqlite.Row], Post[sqlite.Row]]]:
    return await transaction.fetch_all(
        sqlite.select(User).join(Post, on=Post.author_id.references(User.user_id))
    )


async def import_users(transaction: sqlite.Transaction) -> list[User[sqlite.Row]]:
    return await transaction.execute(
        sqlite.insert_many(User, [User(email="Ada"), User(email="Grace")]).returning()
    )
```

Keep `insert(user)`. For batches, replace `insert(rows)` with `insert_many(User, rows)`. Naming the destination lets the type checker catch mixed-model batches more reliably. It also tells it the result type when the list is empty. Runtime checks still reject the wrong model or a fetched value. An empty batch does nothing.

Transactions, SQL compilation, value conversion, and schema operations continue to use the existing implementation. These SQLite examples do not add RETURNING support to MariaDB.

## `complete` creates a value without querying the database

This is useful for a fixture or a snapshot you already have all the values for:

```python
snapshot = sqlite.complete(
    User,
    user_id=UserId(7),
    email="Ada",
    nickname=None,
)
assert_type(snapshot, User[sqlite.Row])
```

`complete` requires every field, even fields with defaults. It validates the values and rejects missing generated values. The result is read-only in the same way as a fetched user. Nested containers can still be mutable.

It does not insert anything or check whether user 7 exists. You cannot pass this value to `insert`.

The type checker knows the result is `User[Row]`, but it does not check these keyword arguments against User's fields. Misspelled names, missing fields, and invalid values raise errors when `complete` runs.

Ordinary construction stays pending-only. Reject `User[Row](...)` and remove unchecked `.construct(...)`.

## `is_complete` tells you which kind of value you have

Suppose a function accepts either a pending user or a fetched user. Before reading a generated ID as a definite `UserId`, it can check:

```python
def identifier(value: User[sqlite.Pending] | User[sqlite.Row]) -> UserId | None:
    if sqlite.is_complete(value):
        assert_type(value, User[sqlite.Row])
        return value.user_id
    return None
```

This checks the state recorded on the object. It returns true for a fetched value or one made with `complete`. It returns false for a pending value, even if you supplied all its fields yourself.

It also tells the type checker that `value` is `User[Row]` inside the `if` block. Outside that block, this guarantee does not apply.

It does not fill in fields, change the object, or contact the database. If you already know you have `User[Row]`, you do not need this check.

## `ready` is for returning queries from helpers

You do not normally need it:

```python
async def list_users(transaction: sqlite.Transaction) -> list[User[sqlite.Row]]:
    return await transaction.fetch_all(sqlite.select(User))
```

It is proposed for functions that return a query instead of executing it:

```python
def users() -> sqlite.ClosedRead[User[sqlite.Row]]:
    query = sqlite.select(User).order_by(User.user_id.asc())
    return sqlite.ready(query)
```

Read this as, "Check the query, then let me return it with a short type annotation that says what it returns."

Why the extra check? While you build a query, its type remembers which tables it references and which tables you have actually included. That helps catch a reference to `Post.title` when you forgot to join Post. An annotation that only says "returns users" can lose that information.

`ready` checks before allowing that shorter annotation. The type checker checks its argument, and at runtime it tries compiling the query to SQL. A missing join or unfinished query fails rather than being repaired for you.

It returns the same query object. It does not run SQL, contact the database, or prove the tables exist. You can pass the result straight to a transaction. Through the returned annotation, you can execute or inspect the query, but cannot keep adding joins and filters. Finish those first.

This is a function, `sqlite.ready(query)`, not a `.ready()` method. It is not a required preparation step for ordinary execution. Execution may compile the query again.

### Other helper annotations

Most application functions do not need these. They are for writing reusable query helpers. The same names would exist under `sqlite` and `mariadb`, without allowing queries to cross between the two.

| Proposed name | What it describes |
| --- | --- |
| `PendingInput[Owner, Result]` | Insert input, including which model it belongs to and what `.returning()` produces |
| `ReadQuery[Scope, Result]` | A read that keeps the table information needed for static checking |
| `OptionalRead[Scope, Result]` | The same, for queries accepted by `fetch_one_or_none` |
| `ClosedRead[Result]` | A read checked by `ready`, whose annotation only needs the result type |
| `ClosedOptional[Result]` | The same, while still allowing `fetch_one_or_none` |
| `Write[Result]` | The existing annotation for an executable write and its result |

For example, this helper keeps the table information, so it does not need `ready`:

```python
async def fetch_all[Scope, Result](
    transaction: sqlite.Transaction,
    query: sqlite.ReadQuery[Scope, Result],
) -> list[Result]:
    return await transaction.fetch_all(query)
```

Replace the old result-only `Select[Result]` annotation rather than keep its missing-table typing hole. These annotations are not constructors. Optional reads must still distinguish no row from a row containing a SQL NULL.

## Checks we must keep

- Use bare model classes as query sources, such as `select(User)`. Some explicit `User[Pending]` source calls still pass ty, so runtime checks must reject them. Aliases and CTEs remain supported.
- Check `__row_type__` when the class is declared. The type checker does not catch every wrong declaration.
- Keep foreign-key checks during metadata binding or Scaffold. Their timing depends on the declaration. Required callable foreign keys without explicit defaults remain outside this change.
- Check both sides of column comparisons for missing tables. Preserve comparisons between compatible nullable columns.
- Reject field reassignment in typing as well as at runtime. Do not promise to freeze nested JSON containers.
- Keep runtime checks for named projection fields. This change does not add more positional projection arguments or general model inheritance.

## Implementation progress

The model portion now uses `Model[State]`, `__row_type__`, and `Row`, with guarded construction, `complete`, and `is_complete`. Existing Python declarations have been migrated. Explicit `insert_many(Model, rows)` is also implemented on both backends, including existing INSERT RETURNING and conflict handling. Empty explicit batches keep their destination and backend while executing no SQL. Native batch callers now use explicit destinations. `insert(user)` accepts only one Pending value; sequence overloads and backend-neutral empty batches are removed.

The read helper annotations and `PendingInput` are implemented. `ready` checks native compilation without database I/O and preserves optional-fetch eligibility. The old result-only `Select` alias is removed; native helper callers now retain their scope or use `ready`.

Column comparisons now retain both owners. Nullable operands and scalar comparison inference remain supported. Frozen-field typing now matches runtime freezing for Pending and Row instances; nested JSON containers remain mutable, and SQL assignments remain allowed.

Correlation typing remains limited. Model `where` and join `on` annotations require local table membership. The stricter owner checks now expose a valid enclosing-table `ON` correlation that previously passed because the right owner was erased. Its native runtime test still passes with an explicit typing suppression. General correlation typing is not redesigned here.

Query-source typing now distinguishes bare declarations from model instances and structural lookalikes, while retaining native aliases and CTEs. Mutation and table-alias factories require declaration evidence. Runtime builders reject lifecycle specializations as sources, including UPDATE and DELETE. All 24 explicit Pending/Row source calls checked across six builders and two backends still pass ty, so this remains a runtime guarantee, not a static one. Wrong-backend mutations reject before evaluating deferred foreign-key targets.

Current guides, embedded examples, and constructor docstrings now use the class-body interface. See the [migration guide](class-body-migration.md) and [checker assessment](typing-compatibility.md) for supported contracts and limits. Copied quick starts have runtime and exact-type controls. Wheel and source-distribution checks run in isolated installs. Final review and the single breaking-change PR remain.

Implement #414 in one PR, reviewing model changes, query typing changes, and documentation separately. The names and snapshot helpers above are approved.

Use test-first changes. Before completion, run the migrated native tests, SQLite and MariaDB integration tests, typing checks, generator checks, lint, and formatting.

Native tests and the caller templates under `typing_probes/` carry the supported contract. Historical research is separate evidence, not a substitute for validating the production implementation.

[All guides](README.md)
