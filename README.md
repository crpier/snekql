# snekql

Write database queries in Python. Get results with types you can check.

snekql is an async query builder for SQLite and MariaDB. You choose the columns,
write the joins, and decide where transactions begin and end. It checks your
Python values and turns your queries into parameterized SQL.

```python
async with db.transaction() as tx:
    users = await tx.fetch_all(
        sqlite.select(User).where(User.email.like("%@example.com")),
    )
    # users: list[User[sqlite.Row]]
```

This uses the `User` model in the example below. Select `User.email` instead,
and the result is `list[str]`. Join another model, and each result includes
both rows. Those types carry through to your application code.

There is no session tracking changes to your objects, and reading an attribute
never loads a relationship. Want to change a row? Write an `update`.
[How this differs from an ORM →](docs/why-not-orm.md)

**Python 3.14+ · SQLite and MariaDB · Type checking with ty**

## Try it

```sh
uv add 'snekql[aiosqlite]'
```

Save this as `app.py` and run `uv run python app.py`. It creates an in-memory
database, inserts a user, and prints `alice@example.com`. You can run it again
without cleaning up any files.

<details>
<summary>A complete, runnable example</summary>

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

</details>

The model describes the Python values and database columns. The migration creates
the table. Opening a connection does **not** create or change your schema.

The [getting-started guide](docs/getting-started.md) walks through each part,
including why the model has `Pending` and `Row` states.

For MariaDB, install `snekql[aiomysql]` and use the `snekql.mariadb` imports.
See [connecting to MariaDB](docs/transactions.md#connect-to-mariadb) for a setup
example. You can install plain `snekql` if you only need to build and inspect SQL.

## What you can do

- **Read and write rows.** Select columns, join tables, group results, insert
  batches, and handle unique-key conflicts. [Queries](docs/queries.md)
- **Keep Python types at the database boundary.** Validate values with Pydantic
  and preserve result types through reads and writes. [Models](docs/models.md)
- **Use SQL when you need it.** Inspect generated SQL or run your own statement
  on the same transaction. [SQL inspection](docs/inspecting-queries.md) ·
  [Raw SQL](docs/raw-sql.md)
- **Make schema changes deliberately.** Commit migration SQL, apply it during
  deployment, and check the live schema against your models.
  [Migrations](docs/migrations.md)

For longer queries, the builder supports [CTEs](docs/ctes.md),
[UNION](docs/unions.md), and [recursive queries](docs/recursive-ctes.md).
Backend differences are documented in the [support table](docs/backend-capabilities.md).

## Is it a fit?

Use snekql if you want async database access and typed queries without handing
relationship loading or schema changes to an ORM. You still need to understand
SQL, write migrations, and choose your transaction boundaries.

It does not provide synchronous access, automatic migrations, or database
backends other than SQLite and MariaDB. **ty 0.0.77 is the supported checker**;
Pyright and mypy do not support the full model interface.
[Typing support and limits](docs/typing-compatibility.md)

snekql is on **0.x**. Minor releases can break compatibility, so pin the minor
version and read the [changelog](CHANGELOG.md) before upgrading. Moving to 0.8?
Start with the [migration guide](docs/class-body-migration.md).

## Where to go next

| I want to… | Read this |
| --- | --- |
| Run my first query | [Getting started](docs/getting-started.md) |
| Define tables and choose column types | [Models](docs/models.md) · [Storage](docs/storage.md) |
| Write queries and understand their results | [Queries](docs/queries.md) · [Typing](docs/typing.md) |
| Add snekql to a web app or worker | [Transactions](docs/transactions.md) · [Service recipes](docs/service-recipes.md) |
| Work with an existing database | [Adoption recipes](docs/service-recipes.md#incremental-adoption) |
| Look up a method or supported feature | [API reference](docs/api-reference.md) · [Backend support](docs/backend-capabilities.md) |

[Browse all documentation →](docs/README.md)

Installed packages also include examples and a compact guide:

```sh
snekql --examples
snekql --example basic
snekql --agent-docs
```

To work on snekql itself, see [contributing and local checks](docs/contributing.md).
