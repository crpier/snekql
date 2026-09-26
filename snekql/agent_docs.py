"""Embedded documentation and examples for coding agents."""

from __future__ import annotations

from importlib.resources import files

from snekql.errors import SnekqlError

EXAMPLE_FILES: dict[str, str] = {
    "basic": "basic.py",
    "mariadb": "mariadb.py",
    "typed_queries": "typed_queries.py",
}

AGENT_DOCS = """# snekql agent guide

snekql is an async typed query builder and runtime for SQLite and MariaDB.

## Quick start

Install `snekql[aiosqlite]`, save the example as `app.py`, and run it with Python
3.14+. It uses an in-memory database, so it is safe to run again. Python 3.14+
defers annotations by default; no future import is needed.

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
    "001_create_user": '''
        CREATE TABLE "user" (
            "id" INTEGER PRIMARY KEY AUTOINCREMENT,
            "email" TEXT NOT NULL
        ) STRICT
    ''',
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

## Core rules

- Import a backend namespace: `from snekql import sqlite` or `from snekql import mariadb`.
- Import model bases, storage constructors, verbs, and runtime classes from that backend namespace.
- Declare `class User[State = sqlite.Pending](sqlite.Model[State])` with
  `__row_type__: ClassVar[sqlite.ReadType[User[sqlite.Row]]]` in its body.
- Construction is Pending-only. SELECT/RETURNING and validated `complete` snapshots
  produce Row values; completeness does not prove persistence.
- Use `insert(user)` for one Pending value and `insert_many(User, rows)` for a batch.
- Preserve `ReadQuery[Scope, Result]` in generic read helpers. For result-only
  helpers, finish composition and return `ready(query)` as `ClosedRead[Result]`.
  Optional-row helpers need `OptionalRead` or `ClosedOptional`; nullable scalars
  do not distinguish SQL NULL from no row. These annotations are not constructors.
- Use bare model declarations as table sources, not lifecycle specializations or
  instances. Native aliases and CTEs are query-only roles.
- Fields are shallowly frozen in Pending and Row states. Nested JSON containers
  remain mutable; SQL writes use explicit assignments rather than field mutation.
- Only ty is supported for this interface. Keep runtime checks for erased types,
  snapshot keyword schemas, declaration consistency, and SQL scope.
- Declare generated columns as `GenCol[T]` and use `PENDING_GENERATION` for values the database fills.
- Own migrations as committed raw SQL. Use `scaffold([Model])` during development,
  then review and paste each statement into the migration declaration. Never call
  `scaffold` at application startup because current model metadata must not rewrite
  historical migration checksums.
- Runtime drivers are optional extras: install `snekql[aiosqlite]` or `snekql[aiomysql]`.

## Copyable examples

```bash
snekql --examples
snekql --example basic
snekql examples
snekql example basic
```
"""


def get_agent_docs() -> str:
    """Return the embedded guide for AI agents and humans."""

    return AGENT_DOCS


def get_examples_listing() -> str:
    """Return a human-readable list of bundled examples."""

    lines = [
        "Bundled snekql examples:",
        *[f"  {name:<14} snekql --example {name}" for name in sorted(EXAMPLE_FILES)],
    ]
    return "\n".join(lines) + "\n"


def get_example_source(example_name: str) -> str:
    """Return the source code for a bundled example."""

    normalized_name = example_name.removesuffix(".py")
    file_name = EXAMPLE_FILES.get(normalized_name)
    if file_name is None:
        file_name = next(
            (
                candidate
                for candidate in EXAMPLE_FILES.values()
                if candidate.removesuffix(".py") == normalized_name
            ),
            None,
        )
    if file_name is None:
        available = ", ".join(sorted(EXAMPLE_FILES))
        message = f"Unknown example `{example_name}`. Use one of: {available}"
        raise SnekqlError(message)

    resource = files("snekql.examples").joinpath(file_name)
    return resource.read_text(encoding="utf-8")
