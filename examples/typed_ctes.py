"""Named, query-only CTEs with token-derived output references."""

import asyncio
from typing import ClassVar

from pydantic import BaseModel

from snekql import sqlite


class User[S = sqlite.Pending](sqlite.Model[S]):
    """Physical application table."""

    __row_type__: ClassVar[sqlite.ReadType[User[sqlite.Row]]]

    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    name: sqlite.Col[str] = sqlite.Text()
    active: sqlite.Col[bool] = sqlite.Integer()


class UserSummary(BaseModel):
    """Final fetched result, not a schema declaration."""

    id: int
    name: str


class ActiveUsers:
    """Nominal role for the named SELECT."""


def active_users(minimum_id: int) -> sqlite.ClosedRead[UserSummary]:
    """Compose one statement; creating the definition performs no IO."""
    user_id = User.id.label("id")
    active = (
        sqlite.select(User)
        .where(User.active.eq(value=True))
        .project(UserSummary, id=user_id, name=User.name)
        .cte(ActiveUsers, name="active_users")
    )
    return sqlite.ready(
        sqlite.select(active)
        .where(active.column(user_id).gt(minimum_id))
        .order_by(active.column(user_id).asc())
    )


async def example() -> list[UserSummary]:
    """Create a disposable dataset and consume the named result contract."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001_users": sqlite.scaffold([User])})
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.insert_many(
                    User,
                    [
                        User(id=1, name="Ada", active=True),
                        User(id=2, name="Linus", active=False),
                        User(id=3, name="Grace", active=True),
                    ],
                )
            )
        async with database.transaction() as transaction:
            return await transaction.fetch_all(active_users(minimum_id=1))


if __name__ == "__main__":
    print(asyncio.run(example()))
