# Run your first query

This guide starts with an empty SQLite database. By the end, you will have a
model, a table, and a query that returns a typed Python object. You do not need
a database server.

## Install

Use Python 3.14 or newer:

```sh
uv add 'snekql[aiosqlite]'
```

The extra installs the SQLite driver. MariaDB uses `snekql[aiomysql]` instead;
[its connection setup](transactions.md#connect-to-mariadb) is separate.

## Copy and run

Save this as `app.py`:

```python
import asyncio
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


MIGRATIONS = {
    "001_create_user": """
        CREATE TABLE "user" (
            "id" INTEGER PRIMARY KEY AUTOINCREMENT,
            "email" TEXT NOT NULL
        ) STRICT
    """,
}


async def main() -> None:
    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:"),
    ) as db:
        await db.migrate(MIGRATIONS)
        await db.verify_migrations(MIGRATIONS)
        await db.verify([User])

        async with db.transaction() as tx:
            await tx.execute(sqlite.insert(User(email="alice@example.com")))
            user = await tx.fetch_one(
                sqlite.select(User).where(User.email.eq("alice@example.com")),
            )
            print(user.email)


asyncio.run(main())
```

Run it:

```sh
uv run python app.py
```

It prints `alice@example.com`. The database exists only for this run, so rerunning
the script is safe. For a file-backed database, pass `Path("app.db")` instead of
`":memory:"`. Its data survives the process, so inserting on every startup is
usually not what you want.

## Read the model

`email: sqlite.Col[str] = sqlite.Text()` says two things: Python sees a string,
and SQLite stores it as text. `GenCol[int]` says the database can fill in the ID.
The generation marker lets you omit that ID when creating a user.

The longer line, `__row_type__`, tells the type checker what a complete row looks
like. You write the table's columns only once.

- `User(email="alice@example.com")` is a `User[sqlite.Pending]`, ready to insert.
  Its generated ID may not be available yet.
- A whole-model SELECT returns `User[sqlite.Row]`. Its ID is an `int`.
- Inserting the Pending value does not fill in that same Python object. Use a
  SELECT or `.returning()` to get the complete row back.

Python 3.14 already defers annotations. No `from __future__ import annotations`
is needed. See [models](models.md) for defaults, optional fields, and snapshots.

## Create the table deliberately

`Database.initialize` connects; it does not create tables.

`migrate(MIGRATIONS)` applies SQL that has not run yet and records its name and
checksum. Keep migration SQL in your source code. Once a migration has run,
append a new one instead of editing it.

The two checks answer different questions:

- `verify_migrations` checks whether the recorded migration history matches your
  application.
- `verify([User])` checks the parts of the live table that snekql can compare with
  your model. It does not prove that all data or every database constraint is valid.

This small script does deployment and application work together. In a service,
[run migrations in a deploy job](service-recipes.md), not in every request.

## Run work in a transaction

The transaction commits when its block finishes normally and rolls back when
an exception leaves the block. Closing the outer database block closes its pool.

`insert` builds a statement; `tx.execute` runs it. Likewise, `select` builds a
query, and `tx.fetch_one` runs it. Building a query alone does no database work.

`fetch_one` expects exactly one row. No rows raises `NoResultError`; multiple
rows raises `MultipleResultsError`. Use `fetch_all` for a list or
`fetch_one_or_none` when a whole row may be missing.

## Check the types

Install the supported checker and check your script:

```sh
uv add --dev ty==0.0.77
uv run ty check app.py
```

Runtime validation still matters. Type checking does not verify your live
schema, prove a row exists, or protect code that deliberately erases its types.

Next: [build queries](queries.md), [define models](models.md), or
[connect an application](transactions.md). The [guide index](README.md) lists
the rest.

[All guides](README.md)
