"""Identical account and referral graphs, loaded through each insertion interface."""

from collections.abc import AsyncGenerator
from typing import Literal

from snekql import sqlite
from snektest import fixture, load_fixture

from scratchpad.paired_advanced import body, dual
from scratchpad.paired_advanced.contracts import UserId


@fixture
async def database(variant: Literal["body", "dual"]) -> AsyncGenerator[sqlite.Database]:
    async with await sqlite.Database.initialize(database=":memory:") as connected:
        scaffold = (
            sqlite.scaffold([body.User, body.Post])
            if variant == "body"
            else dual.storage.scaffold(dual.UserRow, dual.PostRow)
        )
        await connected.migrate({"001": scaffold})
        async with connected.transaction() as native:
            if variant == "body":
                ada = await native.execute(
                    sqlite.insert(body.User(email="Ada", balance=12)).returning()
                )
                grace = await native.execute(
                    sqlite.insert(
                        body.User(
                            email="Grace",
                            balance=12,
                            nickname="Amazing",
                            inviter_id=ada.user_id,
                        )
                    ).returning()
                )
                await native.execute(
                    sqlite.insert(
                        body.User(email="Linus", balance=5, inviter_id=grace.user_id)
                    )
                )
                await native.execute(
                    sqlite.insert(
                        [
                            body.Post(author_id=ada.user_id, title="Notes"),
                            body.Post(author_id=ada.user_id, title="SQL"),
                            body.Post(author_id=grace.user_id, title="Compilers"),
                        ]
                    )
                )
            else:
                transaction = dual.Transaction(native)
                ada = await transaction.execute(
                    dual.insert(dual.User(email="Ada", balance=12)).returning()
                )
                grace = await transaction.execute(
                    dual.insert(
                        dual.User(
                            email="Grace",
                            balance=12,
                            nickname="Amazing",
                            inviter_id=ada.user_id,
                        )
                    ).returning()
                )
                await transaction.execute(
                    dual.insert(
                        dual.User(email="Linus", balance=5, inviter_id=grace.user_id)
                    )
                )
                await transaction.execute(
                    dual.insert_many(
                        [
                            dual.Post(author_id=ada.user_id, title="Notes"),
                            dual.Post(author_id=ada.user_id, title="SQL"),
                            dual.Post(author_id=grace.user_id, title="Compilers"),
                        ]
                    )
                )
        yield connected


@fixture
async def cyclic_database(
    variant: Literal["body", "dual"],
) -> AsyncGenerator[sqlite.Database]:
    connected = await load_fixture(database(variant))
    async with connected.transaction() as native:
        if variant == "body":
            await native.execute(
                sqlite.update(body.User)
                .set(body.User.inviter_id.to(UserId(3)))
                .where(body.User.user_id.eq(UserId(1)))
            )
        else:
            inviter = dual.column(dual.UserRow.inviter_id)
            identity = dual.column(dual.UserRow.user_id)
            await dual.Transaction(native).execute(
                sqlite.update(dual.table(dual.UserRow))
                .set(inviter.to(UserId(3)))
                .where(identity.eq(UserId(1)))
            )
    yield connected
