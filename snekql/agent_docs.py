"""Embedded documentation and examples for coding agents."""

from __future__ import annotations

from importlib.resources import files

from snekql.errors import SnekqlError

EXAMPLE_FILES: dict[str, str] = {
    "basic": "basic.py",
    "typed_queries": "typed_queries.py",
}

AGENT_DOCS = """# snekql agent guide

snekql is an async typed query builder and runtime for SQLite and MariaDB.

## Quick start

```python
from __future__ import annotations

from pathlib import Path

from snekql import sqlite
from snekql.sqlite import Database, Fetched, Pending, insert, scaffold, select


class User[S = Pending](sqlite.Model[S, "User[Fetched]"]):
    id: User.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=sqlite.PENDING_GENERATION,
    )
    email: User.Col[str] = sqlite.Text(nullable=False, unique=True)


async def main() -> None:
    async with await Database.initialize(sqlite.Config(database=Path("app.db"))) as db:
        await db.migrate({"0001_create_user": scaffold([User])})
        await db.verify([User], policy="strict")
        async with db.transaction() as tx:
            await tx.execute(insert(User(email="alice@example.com")))
            user = await tx.fetch_one(
                select(User).where(User.email.eq("alice@example.com")),
            )
            print(user.email)
```

## Core rules

- Import a backend namespace: `from snekql import sqlite` or `from snekql import mariadb`.
- Import model bases, storage constructors, verbs, and runtime classes from that backend namespace.
- Declare generated columns as `GenCol[T]` and use `PENDING_GENERATION` for values the database fills.
- Own migrations as raw SQL. Use `scaffold([Model])` only to produce the first migration body.
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
