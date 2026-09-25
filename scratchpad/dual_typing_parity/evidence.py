"""Compare schema and SQL only; isolated callers provide the separate typing evidence."""

import sys
from hashlib import sha256
from importlib.metadata import version
from json import dumps
from typing import Any

from anyio import Path, run, to_thread
from pydantic import BaseModel
from snekql import sqlite

from scratchpad.dual_typing_parity import bridge, current, dual


class Summary(BaseModel):
    balance: int
    email: str


class Role:
    pass


def compiled_samples(*, paired: bool) -> dict[str, sqlite.CompiledQuery]:
    """Erase declaration-specific owners here only to compare compiled artifacts."""
    users: Any = bridge.table(dual.UserRow) if paired else current.User
    posts: Any = bridge.table(dual.PostRow) if paired else current.Post
    identity: Any = (
        bridge.column(dual.UserRow.user_id) if paired else current.User.user_id
    )
    email: Any = bridge.column(dual.UserRow.email) if paired else current.User.email
    balance: Any = (
        bridge.column(dual.UserRow.balance) if paired else current.User.balance
    )
    author: Any = (
        bridge.column(dual.PostRow.author_id) if paired else current.Post.author_id
    )
    title: Any = bridge.column(dual.PostRow.title) if paired else current.Post.title
    insertion: Any = (
        bridge.insert(dual.User(email="A", balance=12))
        if paired
        else sqlite.insert(current.User(email="A", balance=12))
    )
    source = sqlite.select(users).all().project(Summary, email=email, balance=balance)
    queries: dict[str, Any] = {
        "model": sqlite.select(users).all(),
        "tuple": sqlite.select(identity, email).all(),
        "inner": sqlite.select(users).join(posts, on=author.references(identity)).all(),
        "left": sqlite.select(users)
        .left_join(posts, on=author.references(identity))
        .all(),
        "ordered": sqlite.select(email)
        .all()
        .distinct()
        .order_by(email.desc())
        .limit(2)
        .offset(1),
        "arithmetic": sqlite.select(balance.add(3)).all(),
        "named": source,
        "cte": sqlite.select(source.cte(Role, name="summary")).all(),
        "union": source.union_all(source),
        "exists": sqlite.select(users).where(
            sqlite.exists(sqlite.select(title).where(author.eq_col(identity)))
        ),
        "insert": insertion.returning(),
        "upsert": insertion.on_conflict(
            email, action=sqlite.DoUpdate(balance.to(18))
        ).returning(),
        "update": sqlite.update(users).set(balance.to(18)).all().returning(),
        "delete": sqlite.delete(users).all().returning(),
    }
    return {name: query.compile() for name, query in queries.items()}


async def main() -> None:
    directory = Path(__file__).parent
    native = compiled_samples(paired=False)
    paired = compiled_samples(paired=True)
    if native != paired:
        raise sqlite.QueryConstructionError("A matched query changed SQL or parameters")
    current_schema = sqlite.scaffold([current.User, current.Post])
    dual_schema = dual.sqlite.scaffold(dual.UserRow, dual.PostRow)
    if current_schema != dual_schema:
        raise sqlite.ModelDeclarationError("The compared storage declarations differ")
    files = [path async for path in directory.glob("*.py")]
    report = {
        "python": sys.version,
        "ty": await to_thread.run_sync(version, "ty"),
        "ruff": await to_thread.run_sync(version, "ruff"),
        "sources": {
            path.name: sha256(await path.read_bytes()).hexdigest() for path in files
        },
        "scaffold": current_schema,
        "compiled_pairs": {
            name: {"sql": query.sql, "params": query.params}
            for name, query in native.items()
        },
    }
    await (directory / "evidence.json").write_text(dumps(report, indent=2) + "\n")
    print(f"Matching two-model scaffold and {len(native)} SQL/parameter pairs")


if __name__ == "__main__":
    run(main)
