"""Native operators exercised against storage derived from dual declarations."""

from typing import assert_type

from pydantic import BaseModel
from snekql import sqlite
from snektest import assert_eq, assert_isinstance, load_fixture, test

from scratchpad.dual_typing_parity import bridge, dual
from scratchpad.dual_typing_parity.test_bridge import database, joined_database


class Summary(BaseModel):
    balance: int
    email: str


class Group(BaseModel):
    balance: int
    total: int


class Walk(BaseModel):
    depth: int


class FirstRole:
    pass


class SecondRole:
    pass


@test(mark="medium")
async def aliases_return_distinct_dual_model_slots() -> None:
    connected = await load_fixture(database())
    first = sqlite.alias(bridge.table(dual.UserRow), FirstRole, name="first")
    second = sqlite.alias(bridge.table(dual.UserRow), SecondRole, name="second")
    identity = bridge.column(dual.UserRow.user_id)

    async with connected.transaction() as transaction:
        rows = await bridge.Transaction(transaction).fetch_all(
            sqlite.select(first)
            .join(second, on=first.column(identity).eq_col(second.column(identity)))
            .all()
        )
    assert_type(rows, list[tuple[dual.UserRow, dual.UserRow]])
    assert_eq(
        [(type(first), type(second)) for first, second in rows],
        [(dual.UserRow, dual.UserRow)],
    )
    assert_eq([(first.email, second.email) for first, second in rows], [("Ada", "Ada")])


@test(mark="medium")
async def ordered_pagination_preserves_scalar_values() -> None:
    connected = await load_fixture(joined_database())
    email = bridge.column(dual.UserRow.email)

    async with connected.transaction() as transaction:
        rows = await bridge.Transaction(transaction).fetch_all(
            sqlite.select(email)
            .all()
            .distinct()
            .order_by(email.asc())
            .offset(1)
            .limit(1)
        )
    assert_type(rows, list[str])
    assert_eq(rows, ["Grace"])


@test(mark="medium")
async def grouped_having_materializes_named_results() -> None:
    connected = await load_fixture(joined_database())
    users = bridge.table(dual.UserRow)
    balance = bridge.column(dual.UserRow.balance)

    async with connected.transaction() as transaction:
        rows = await bridge.Transaction(transaction).fetch_all(
            sqlite.select(users)
            .all()
            .project(Group, balance=balance, total=users.count_all())
            .group_by(balance)
            .having(users.count_all().gt(0))
            .order_by(balance.asc())
        )
    assert_type(rows, list[Group])
    assert_eq(rows, [Group(balance=12, total=1), Group(balance=25, total=1)])


@test(mark="medium")
async def arithmetic_executes_as_a_native_expression() -> None:
    connected = await load_fixture(database())
    balance = bridge.column(dual.UserRow.balance)

    async with connected.transaction() as transaction:
        rows = await bridge.Transaction(transaction).fetch_all(
            sqlite.select(balance.add(3)).all()
        )
    assert_type(rows, list[int])
    assert_eq(rows, [15])


@test(mark="medium")
async def coalesce_removes_nullable_result() -> None:
    connected = await load_fixture(database())
    nickname = bridge.column(dual.UserRow.nickname)

    async with connected.transaction() as transaction:
        rows = await bridge.Transaction(transaction).fetch_all(
            sqlite.select(nickname.coalesce("anonymous")).all()
        )
    assert_type(rows, list[str])
    assert_eq(rows, ["anonymous"])


@test(mark="medium")
async def case_uses_the_native_value_contract() -> None:
    connected = await load_fixture(database())
    balance = bridge.column(dual.UserRow.balance)

    async with connected.transaction() as transaction:
        rows = await bridge.Transaction(transaction).fetch_all(
            sqlite.select(sqlite.case(balance.gt(10), then=balance, otherwise=0)).all()
        )
    assert_type(rows, list[int])
    assert_eq(rows, [12])


@test(mark="medium")
async def correlated_exists_filters_dual_models() -> None:
    connected = await load_fixture(joined_database())
    author = bridge.column(dual.PostRow.author_id)
    identity = bridge.column(dual.UserRow.user_id)
    title = bridge.column(dual.PostRow.title)

    async with connected.transaction() as transaction:
        rows = await bridge.Transaction(transaction).fetch_all(
            sqlite.select(bridge.table(dual.UserRow)).where(
                sqlite.exists(sqlite.select(title).where(author.eq_col(identity)))
            )
        )
    assert_type(rows, list[dual.UserRow])
    assert_eq([row.email for row in rows], ["Ada"])


@test(mark="medium")
async def cte_reuses_native_labels() -> None:
    connected = await load_fixture(database())
    email = bridge.column(dual.UserRow.email).label("email")
    balance = bridge.column(dual.UserRow.balance)
    source = (
        sqlite.select(bridge.table(dual.UserRow))
        .all()
        .project(Summary, email=email, balance=balance)
        .cte(FirstRole, name="summary")
    )

    async with connected.transaction() as transaction:
        rows = await bridge.Transaction(transaction).fetch_all(
            sqlite.select(source).where(source.column(email).eq("Ada"))
        )
    assert_type(rows, list[Summary])
    assert_eq(rows, [Summary(email="Ada", balance=12)])


@test(mark="medium")
async def union_all_preserves_named_rows() -> None:
    connected = await load_fixture(database())
    email = bridge.column(dual.UserRow.email)
    balance = bridge.column(dual.UserRow.balance)
    source = (
        sqlite.select(bridge.table(dual.UserRow))
        .all()
        .project(Summary, email=email, balance=balance)
    )

    async with connected.transaction() as transaction:
        rows = await bridge.Transaction(transaction).fetch_all(source.union_all(source))
    assert_type(rows, list[Summary])
    assert_eq(
        rows, [Summary(email="Ada", balance=12), Summary(email="Ada", balance=12)]
    )


@test(mark="medium")
async def recursive_cte_uses_the_native_recursion_operator() -> None:
    connected = await load_fixture(database())
    depth = sqlite.literal(0).label("depth")
    anchor = sqlite.select(bridge.table(dual.UserRow)).all().project(Walk, depth=depth)
    walk = sqlite.recursive_cte(anchor, FirstRole, name="walk").step(
        lambda previous: (
            sqlite.select(previous)
            .where(previous.column(depth).lt(3))
            .project(Walk, depth=previous.column(depth).add(1))
        )
    )

    async with connected.transaction() as transaction:
        rows = await bridge.Transaction(transaction).fetch_all(
            sqlite.select(walk).all().order_by(walk.column(depth).asc())
        )
    assert_type(rows, list[Walk])
    assert_eq([row.depth for row in rows], [0, 1, 2, 3])


@test(mark="medium")
async def conflict_updates_only_the_selected_field() -> None:
    connected = await load_fixture(database())
    email = bridge.column(dual.UserRow.email)
    balance = bridge.column(dual.UserRow.balance)

    async with connected.transaction() as transaction:
        row = await bridge.Transaction(transaction).execute(
            bridge.insert(dual.User(email="Ada", balance=0))
            .on_conflict(email, action=sqlite.DoUpdate(balance.to(18)))
            .returning()
        )
    assert_type(row, dual.UserRow)
    assert_eq((type(row), row.balance), (dual.UserRow, 18))


@test(mark="medium")
async def delete_returning_materializes_dual_rows() -> None:
    connected = await load_fixture(database())
    async with connected.transaction() as transaction:
        rows = await bridge.Transaction(transaction).execute(
            sqlite.delete(bridge.table(dual.UserRow)).all().returning()
        )
    assert_type(rows, list[dual.UserRow])
    assert_isinstance(rows[0], dual.UserRow)
    assert_eq(rows[0].email, "Ada")


@test(mark="medium")
async def named_returning_uses_the_application_contract() -> None:
    connected = await load_fixture(database())
    email = bridge.column(dual.UserRow.email)
    balance = bridge.column(dual.UserRow.balance)

    async with connected.transaction() as transaction:
        rows = await bridge.Transaction(transaction).execute(
            sqlite.update(bridge.table(dual.UserRow))
            .set(balance.to(18))
            .all()
            .returning_as(Summary, email=email, balance=balance)
        )
    assert_type(rows, list[Summary])
    assert_eq(rows, [Summary(email="Ada", balance=18)])


@test(mark="medium")
async def validated_raw_results_do_not_depend_on_model_layout() -> None:
    connected = await load_fixture(database())
    async with connected.transaction() as transaction:
        rows = await transaction.fetch_all(
            sqlite.raw("SELECT email, balance FROM users", validate=Summary)
        )
    assert_type(rows, list[Summary])
    assert_eq(rows, [Summary(email="Ada", balance=12)])


@test(mark="medium")
async def scalar_subquery_retains_its_nullable_slot() -> None:
    connected = await load_fixture(database())
    email = bridge.column(dual.UserRow.email)
    balance = bridge.column(dual.UserRow.balance)
    async with connected.transaction() as transaction:
        rows = await bridge.Transaction(transaction).fetch_all(
            sqlite.select(
                email, sqlite.scalar(sqlite.select(balance).all().limit(1))
            ).all()
        )
    assert_type(rows, list[tuple[str, int | None]])
    assert_eq(rows, [("Ada", 12)])
