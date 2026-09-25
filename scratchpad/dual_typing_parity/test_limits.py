"""Accepted typing counterexamples and the runtime checks that do or do not catch them."""

from typing import Any, ClassVar, assert_type

from snekql import sqlite
from snektest import assert_eq, assert_not_isinstance, assert_raises, load_fixture, test

from scratchpad.dual_typing_parity import bridge, current, dual
from scratchpad.dual_typing_parity.test_advanced import Summary
from scratchpad.dual_typing_parity.test_bridge import database


@test(mark="medium")
async def native_consumer_does_not_apply_the_bridge_decoder() -> None:
    connected = await load_fixture(database())
    async with connected.transaction() as transaction:
        rows = await transaction.fetch_all(
            sqlite.select(bridge.table(dual.UserRow)).all()
        )
    assert_type(rows, list[dual.UserRow])
    assert_not_isinstance(rows[0], dual.UserRow)


@test(mark="medium")
async def incorrect_native_result_witness_is_not_runtime_checked() -> None:
    connected = await load_fixture(database())

    class Wrong[State = sqlite.Pending](
        sqlite.Model[State, "current.Post[sqlite.Fetched]"]
    ):
        __tablename__ = "users"
        user_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        email: sqlite.Col[str] = sqlite.Text()
        balance: sqlite.Col[int] = sqlite.Integer()
        nickname: sqlite.Col[str | None] = sqlite.Text()

    async with connected.transaction() as transaction:
        rows = await transaction.fetch_all(sqlite.select(Wrong).all())
    assert_type(rows, list[current.Post[sqlite.Fetched]])
    assert_not_isinstance(rows[0], current.Post)
    assert_eq(type(rows[0]), Wrong)


@test(mark="fast")
def incorrect_dual_pair_is_runtime_checked() -> None:
    class Wrong(dual.sqlite.Model):
        __row__: ClassVar[type[dual.PostRow]]
        email: dual.sqlite.Col[str] = dual.sqlite.Text()

    with assert_raises(sqlite.ModelDeclarationError):
        dual.sqlite.insert(Wrong(email="A"))


@test(mark="fast")
def missing_refinement_fails_schema_binding() -> None:
    class Missing(dual.User, bridge.Row):
        table_name = "missing_refinement"

    with assert_raises(sqlite.ModelDeclarationError):
        dual.sqlite.scaffold(Missing)


@test(mark="fast")
def subtype_constructor_can_require_more_than_input_constructor() -> None:
    def factory(model: type[dual.User]) -> dual.User:
        return model(email="A", balance=12)

    with assert_raises(sqlite.ModelValidationError):
        factory(dual.UserRow)


@test(mark="fast")
def generic_specialization_is_not_an_isinstance_discriminator() -> None:
    pending = current.User(email="A", balance=12)
    with assert_raises(TypeError):
        isinstance(pending, current.User[sqlite.Fetched])


@test(mark="fast")
def incomplete_expression_scope_is_rejected_at_compilation() -> None:
    query = sqlite.select(current.User).where(
        current.User.email.eq_col(current.Post.title)
    )
    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


@test(mark="fast")
def named_projection_domains_remain_runtime_checked() -> None:
    email = bridge.column(dual.UserRow.email)
    balance = bridge.column(dual.UserRow.balance)
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(bridge.table(dual.UserRow)).all().project(
            Summary, email=balance, balance=email
        )


@test(mark="medium")
async def native_fetched_reinsertion_is_rejected_after_erasure() -> None:
    connected = await load_fixture(database())
    async with connected.transaction() as transaction:
        row = await transaction.fetch_one(sqlite.select(current.User).all())
    erased_insert: Any = sqlite.insert
    with assert_raises(sqlite.QueryConstructionError):
        erased_insert(row)


@test(mark="medium")
async def dual_complete_value_remains_insertable() -> None:
    connected = await load_fixture(database())
    row = dual.UserRow(user_id=dual.UserId(42), email="Complete", balance=7)
    async with connected.transaction() as transaction:
        inserted = await bridge.Transaction(transaction).execute(
            bridge.insert(row).returning()
        )
    assert_type(inserted, dual.UserRow)
    assert_eq((type(inserted), inserted.user_id), (dual.UserRow, dual.UserId(42)))


@test(mark="medium")
async def unchecked_read_does_not_claim_a_dual_row() -> None:
    connected = await load_fixture(database())
    async with connected.transaction() as transaction:
        rows = await bridge.Transaction(transaction).fetch_all(
            sqlite.select(bridge.table(dual.UserRow)).where(
                bridge.column(dual.UserRow.email).eq("Ada")
            ),
            validate=False,
        )
    assert_type(rows, list[object])
    assert_not_isinstance(rows[0], dual.UserRow)
    assert_eq(vars(rows[0])["balance"], 12)


@test(mark="fast")
def native_mixed_bulk_inputs_fail_construction() -> None:
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.insert(
            [
                current.User(email="A", balance=12),
                current.Post(author_id=dual.UserId(1), title="x"),
            ]
        )


@test(mark="fast")
def bridge_mixed_bulk_inputs_fail_construction() -> None:
    with assert_raises(sqlite.QueryConstructionError):
        bridge.insert_many(
            [
                dual.User(email="A", balance=12),
                dual.Post(author_id=dual.UserId(1), title="x"),
            ]
        )


@test(mark="fast")
def erased_select_helper_does_not_establish_source_completeness() -> None:
    def ready(query: sqlite.Select[tuple[str, str]]) -> sqlite.Select[tuple[str, str]]:
        return query

    query = ready(sqlite.select(current.User.email, current.Post.title).all())
    with assert_raises(sqlite.QueryCompilationError):
        query.compile()
