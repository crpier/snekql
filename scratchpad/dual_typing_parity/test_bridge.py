"""Native query reuse must materialize the dual result it promises."""

from collections.abc import AsyncGenerator
from typing import assert_type

from snekql import sqlite
from snektest import assert_eq, assert_isinstance, fixture, load_fixture, test

from scratchpad.dual_typing_parity import bridge, dual


@fixture
async def database() -> AsyncGenerator[sqlite.Database]:
    async with await sqlite.Database.initialize(database=":memory:") as connected:
        await connected.migrate({"001": dual.sqlite.scaffold(dual.UserRow)})
        async with connected.transaction() as transaction:
            await dual.sqlite.Transaction(transaction).execute(
                dual.sqlite.insert(dual.User(email="Ada", balance=12)).returning()
            )
        yield connected


@test(mark="medium")
async def model_read_materializes_the_promised_dual_row() -> None:
    connected = await load_fixture(database())
    async with connected.transaction() as transaction:
        rows = await bridge.Transaction(transaction).fetch_all(
            sqlite.select(bridge.table(dual.UserRow)).all()
        )
    assert_type(rows, list[dual.UserRow])
    assert_isinstance(rows[0], dual.UserRow)
    assert_eq(rows[0].email, "Ada")


@test(mark="medium")
async def tuple_read_keeps_scalar_slots() -> None:
    connected = await load_fixture(database())
    async with connected.transaction() as transaction:
        rows = await bridge.Transaction(transaction).fetch_all(
            sqlite.select(
                bridge.column(dual.UserRow.email),
                bridge.column(dual.UserRow.balance),
            ).all()
        )
    assert_type(rows, list[tuple[str, int]])
    assert_eq(rows, [("Ada", 12)])


@fixture
async def joined_database() -> AsyncGenerator[sqlite.Database]:
    async with await sqlite.Database.initialize(database=":memory:") as connected:
        await connected.migrate(
            {"001": dual.sqlite.scaffold(dual.UserRow, dual.PostRow)}
        )
        async with connected.transaction() as native:
            transaction = dual.sqlite.Transaction(native)
            user = await transaction.execute(
                dual.sqlite.insert(dual.User(email="Ada", balance=12)).returning()
            )
            await transaction.execute(
                dual.sqlite.insert(dual.Post(author_id=user.user_id, title="Notes"))
            )
            await transaction.execute(
                dual.sqlite.insert(dual.User(email="Grace", balance=25))
            )
        yield connected


@test(mark="medium")
async def model_join_materializes_both_dual_classes() -> None:
    connected = await load_fixture(joined_database())
    async with connected.transaction() as transaction:
        rows = await bridge.Transaction(transaction).fetch_all(
            sqlite.select(bridge.table(dual.UserRow))
            .join(
                bridge.table(dual.PostRow),
                on=bridge.column(dual.PostRow.author_id).references(
                    bridge.column(dual.UserRow.user_id)
                ),
            )
            .all()
        )
    assert_type(rows, list[tuple[dual.UserRow, dual.PostRow]])
    assert_eq(
        [(type(user), type(post)) for user, post in rows],
        [(dual.UserRow, dual.PostRow)],
    )
    assert_eq([(user.email, post.title) for user, post in rows], [("Ada", "Notes")])


@test(mark="medium")
async def left_join_materializes_missing_dual_row_as_none() -> None:
    connected = await load_fixture(joined_database())
    async with connected.transaction() as transaction:
        rows = await bridge.Transaction(transaction).fetch_all(
            sqlite.select(bridge.table(dual.UserRow))
            .left_join(
                bridge.table(dual.PostRow),
                on=bridge.column(dual.PostRow.author_id).references(
                    bridge.column(dual.UserRow.user_id)
                ),
            )
            .all()
            .order_by(bridge.column(dual.UserRow.user_id).asc())
        )
    assert_type(rows, list[tuple[dual.UserRow, dual.PostRow | None]])
    assert_eq(
        [(user.email, None if post is None else post.title) for user, post in rows],
        [("Ada", "Notes"), ("Grace", None)],
    )


@test(mark="medium")
async def update_returning_materializes_a_dual_row() -> None:
    connected = await load_fixture(database())
    async with connected.transaction() as transaction:
        rows = await bridge.Transaction(transaction).execute(
            sqlite.update(bridge.table(dual.UserRow))
            .set(bridge.column(dual.UserRow.balance).to(18))
            .all()
            .returning()
        )
    assert_type(rows, list[dual.UserRow])
    assert_isinstance(rows[0], dual.UserRow)
    assert_eq(rows[0].balance, 18)


@test(mark="medium")
async def implicit_insert_returning_materializes_a_dual_row() -> None:
    connected = await load_fixture(database())
    async with connected.transaction() as transaction:
        row = await bridge.Transaction(transaction).execute(
            bridge.insert(dual.User(email="Grace", balance=25)).returning()
        )
    assert_type(row, dual.UserRow)
    assert_isinstance(row, dual.UserRow)
    assert_eq(row.email, "Grace")


@test(mark="medium")
async def optional_model_read_retains_dual_identity() -> None:
    connected = await load_fixture(database())
    async with connected.transaction() as transaction:
        row = await bridge.Transaction(transaction).fetch_one_or_none(
            sqlite.select(bridge.table(dual.UserRow)).where(
                bridge.column(dual.UserRow.email).eq("Ada")
            )
        )
    assert_type(row, dual.UserRow | None)
    assert_isinstance(row, dual.UserRow)


@test(mark="medium")
async def bulk_returning_materializes_dual_rows() -> None:
    connected = await load_fixture(database())
    async with connected.transaction() as transaction:
        rows = await bridge.Transaction(transaction).execute(
            bridge.insert_many(
                [
                    dual.User(email="Grace", balance=25),
                    dual.User(email="Linus", balance=6),
                ]
            ).returning()
        )
    assert_type(rows, list[dual.UserRow])
    assert_eq(
        [(type(row), row.email) for row in rows],
        [(dual.UserRow, "Grace"), (dual.UserRow, "Linus")],
    )


@test(mark="medium")
async def streaming_keeps_dual_rows_in_each_batch() -> None:
    connected = await load_fixture(joined_database())
    emails: list[str] = []
    async with (
        connected.transaction() as transaction,
        bridge.Transaction(transaction).fetch_chunks(
            sqlite.select(bridge.table(dual.UserRow))
            .all()
            .order_by(bridge.column(dual.UserRow.user_id).asc()),
            size=1,
        ) as chunks,
    ):
        async for batch in chunks:
            assert_type(batch, list[dual.UserRow])
            assert_isinstance(batch[0], dual.UserRow)
            emails.extend(row.email for row in batch)
    assert_eq(emails, ["Ada", "Grace"])
