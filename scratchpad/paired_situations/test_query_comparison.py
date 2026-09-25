"""Query differences exercised at execution, not inferred from constructor tests."""

from typing import assert_type

from snekql import sqlite
from snektest import assert_eq, assert_raises, test

from scratchpad.class_body_usage import current as original
from scratchpad.paired_situations import body as b
from scratchpad.paired_situations import dual as d
from scratchpad.paired_situations.test_body import database as body_database


@test(mark="medium")
async def body_protocol_helper_preserves_exact_row() -> None:
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001": sqlite.scaffold([b.Counter])})
        async with database.transaction() as transaction:
            counter = await b.execute_write(
                transaction, b.insert_via_protocol(b.Counter())
            )
    assert_type(counter, b.Counter[sqlite.Fetched])
    assert_eq((counter.counter_id, counter.count), (1, 0))


@test(mark="fast")
def body_instance_source_is_a_runtime_only_rejection() -> None:
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(b.User(email="A"))


@test(mark="fast")
def original_instance_source_has_the_same_runtime_rejection() -> None:
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(original.User(email="A"))


@test(mark="medium")
async def body_model_join_returns_both_models() -> None:
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001": sqlite.scaffold([b.User, b.Post])})
        async with database.transaction() as transaction:
            user = await b.create_user(transaction, "A")
            await b.create_post(transaction, user.user_id, "Notes")
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(
                sqlite.select(b.User)
                .join(b.Post, on=b.Post.author_id.references(b.User.user_id))
                .all()
            )
    assert_type(rows, list[tuple[b.User[sqlite.Fetched], b.Post[sqlite.Fetched]]])
    assert_eq([(user.email, post.title) for user, post in rows], [("A", "Notes")])


@test(mark="medium")
async def dual_model_join_retains_only_selected_model() -> None:
    async with await d.sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001": d.sqlite.scaffold(d.UserRow, d.PostRow)})
        async with database.transaction() as transaction:
            user = await d.create_user(transaction, "A")
            await d.create_post(transaction, user.user_id, "Notes")
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(
                d.sqlite.select(d.UserRow)
                .join(d.PostRow, on=d.PostRow.author_id.references(d.UserRow.user_id))
                .all()
            )
    assert_type(rows, list[d.UserRow])
    assert_eq([user.email for user in rows], ["A"])


@test(mark="medium")
async def body_tuple_projection_materializes_exact_values() -> None:
    from snektest import load_fixture

    database = await load_fixture(body_database())
    async with database.transaction() as transaction:
        await b.create_user(transaction, "A")
    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            sqlite.select(b.User.user_id, b.User.email).all()
        )
    assert_type(rows, list[tuple[b.UserId, str]])
    assert_eq(rows, [(b.UserId(1), "A")])


@test(mark="medium")
async def body_left_join_materializes_a_missing_model_as_none() -> None:
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001": sqlite.scaffold([b.User, b.Post])})
        async with database.transaction() as transaction:
            await b.create_user(transaction, "A")
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(
                sqlite.select(b.User)
                .left_join(b.Post, on=b.Post.author_id.references(b.User.user_id))
                .all()
            )
    assert_type(
        rows, list[tuple[b.User[sqlite.Fetched], b.Post[sqlite.Fetched] | None]]
    )
    assert_eq([(user.email, post) for user, post in rows], [("A", None)])


@test(mark="medium")
async def body_write_helper_accepts_update_returning() -> None:
    from snektest import load_fixture

    database = await load_fixture(body_database())
    async with database.transaction() as transaction:
        user = await b.create_user(transaction, "A")
    async with database.transaction() as transaction:
        rows = await b.execute_write(
            transaction,
            sqlite.update(b.User)
            .set(b.User.display_name.to("Ada"))
            .where(b.User.user_id.eq(user.user_id))
            .returning(),
        )
    assert_type(rows, list[b.User[sqlite.Fetched]])
    assert_eq([row.display_name for row in rows], ["Ada"])


@test(mark="medium")
async def dual_complete_value_can_supply_an_insert() -> None:
    from snektest import load_fixture

    from scratchpad.paired_situations.test_dual import database as dual_database

    database = await load_fixture(dual_database())
    complete = d.UserRow(user_id=d.UserId(42), email="A")
    async with database.transaction() as transaction:
        row = await transaction.execute(d.sqlite.insert(complete).returning())
    assert_type(row, d.UserRow)
    assert_eq((row.user_id, row.email), (d.UserId(42), "A"))


@test(mark="fast")
def original_specialized_source_has_the_same_runtime_rejection() -> None:
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(original.User[sqlite.Fetched]).all()
