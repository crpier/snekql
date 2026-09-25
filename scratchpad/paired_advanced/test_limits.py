"""Application-level checks of the limitations that could affect the comparison."""

from typing import Any, ClassVar, Literal, assert_type

from snekql import sqlite
from snektest import (
    Param,
    assert_eq,
    assert_not_isinstance,
    assert_raises,
    load_fixture,
    test,
)

from scratchpad.class_body_usage.sqlite import Model, ReadType
from scratchpad.paired_advanced import body, dual, helpers
from scratchpad.paired_advanced.contracts import AccountSummary, UserId
from scratchpad.paired_advanced.fixtures import database


@test(mark="fast")
def body_rejects_an_unrelated_result_witness_at_declaration() -> None:
    with assert_raises(sqlite.ModelDeclarationError):

        class Wrong[State = sqlite.Pending](Model[State]):
            __read_type__: ClassVar[ReadType[body.Post[sqlite.Fetched]]]
            email: sqlite.Col[str] = sqlite.Text()


@test(mark="fast")
def dual_rejects_an_unrelated_result_witness_at_insertion() -> None:
    class Wrong(dual.storage.Model):
        __row__: ClassVar[type[dual.PostRow]]
        email: dual.storage.Col[str] = dual.storage.Text()

    with assert_raises(sqlite.ModelDeclarationError):
        dual.storage.insert(Wrong(email="A"))


@test(mark="medium")
async def body_union_bound_helper_preserves_fetched_specialization() -> None:
    connected = await load_fixture(database("body"))
    async with connected.transaction() as transaction:
        row = await transaction.fetch_one(
            sqlite.select(body.User).where(body.User.email.eq("Ada"))
        )
    checked = helpers.body_checked(row)
    assert_type(checked, body.User[sqlite.Fetched])
    assert_eq(checked.identity(), UserId(1))


@test(mark="medium")
async def dual_input_bound_helper_preserves_row_class() -> None:
    connected = await load_fixture(database("dual"))
    async with connected.transaction() as native:
        row = await dual.Transaction(native).fetch_one(
            sqlite.select(dual.table(dual.UserRow)).where(
                dual.column(dual.UserRow.email).eq("Ada")
            )
        )
    checked = helpers.dual_checked(row)
    assert_type(checked, dual.UserRow)
    assert_eq(checked.identity(), UserId(1))


@test(mark="medium")
async def native_transaction_still_bypasses_dual_materialization() -> None:
    connected = await load_fixture(database("dual"))
    async with connected.transaction() as transaction:
        rows = await transaction.fetch_all(
            sqlite.select(dual.table(dual.UserRow)).all()
        )
    assert_type(rows, list[dual.UserRow])
    assert_not_isinstance(rows[0], dual.UserRow)


@test(mark="medium")
async def body_protocol_insertion_keeps_exact_result() -> None:
    connected = await load_fixture(database("body"))
    async with connected.transaction() as transaction:
        row = await transaction.execute(
            helpers.body_insert(body.User(email="New", balance=7))
        )
    assert_type(row, body.User[sqlite.Fetched])
    assert_eq((type(row), row.email), (body.User, "New"))


@test(mark="medium")
async def dual_protocol_insertion_keeps_exact_result() -> None:
    connected = await load_fixture(database("dual"))
    async with connected.transaction() as native:
        row = await dual.Transaction(native).execute(
            helpers.dual_insert(dual.User(email="New", balance=7))
        )
    assert_type(row, dual.UserRow)
    assert_eq((type(row), row.email), (dual.UserRow, "New"))


@test(mark="medium")
async def body_rejects_complete_insertion_after_erasure() -> None:
    connected = await load_fixture(database("body"))
    async with connected.transaction() as transaction:
        row = await transaction.fetch_one(
            sqlite.select(body.User).where(body.User.user_id.eq(UserId(1)))
        )
    erased: Any = sqlite.insert
    with assert_raises(sqlite.QueryConstructionError):
        erased(row)


@test(mark="medium")
async def dual_accepts_complete_insertion() -> None:
    connected = await load_fixture(database("dual"))
    async with connected.transaction() as native:
        row = await dual.Transaction(native).execute(
            dual.insert(
                dual.UserRow(user_id=UserId(42), email="Complete", balance=7)
            ).returning()
        )
    assert_eq((type(row), row.user_id), (dual.UserRow, UserId(42)))


@test(mark="fast")
def body_specialization_does_not_support_isinstance() -> None:
    with assert_raises(TypeError):
        isinstance(body.User(email="A", balance=1), body.User[sqlite.Fetched])


@test(mark="fast")
def body_projection_keywords_are_runtime_validated() -> None:
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(body.User).all().project(
            AccountSummary, email=body.User.balance, balance=body.User.email
        )


@test(mark="fast")
def dual_projection_keywords_are_runtime_validated() -> None:
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(dual.table(dual.UserRow)).all().project(
            AccountSummary,
            email=dual.column(dual.UserRow.balance),
            balance=dual.column(dual.UserRow.email),
        )


@test(mark="fast")
def body_right_hand_owner_is_runtime_validated() -> None:
    query = sqlite.select(body.User).where(body.User.email.eq_col(body.Post.title))
    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


@test(mark="fast")
def dual_right_hand_owner_is_runtime_validated() -> None:
    email, title = dual.column(dual.UserRow.email), dual.column(dual.PostRow.title)
    query = sqlite.select(dual.table(dual.UserRow)).where(email.eq_col(title))
    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


@test(mark="fast")
def body_instance_mutation_is_rejected_at_runtime() -> None:
    pending = body.User(email="A", balance=1)
    with assert_raises(sqlite.FrozenModelError):
        pending.email = "B"


@test(mark="fast")
def body_instance_source_is_rejected_at_runtime() -> None:
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(body.User(email="A", balance=1))


@test(mark="fast")
def body_specialized_source_is_rejected_at_runtime() -> None:
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(body.User[sqlite.Fetched])


@test(
    [
        Param[Literal["body", "dual"]](value="body", name="body"),
        Param[Literal["body", "dual"]](value="dual", name="dual"),
    ],
    mark="medium",
)
async def validated_raw_results_are_independent_of_declaration_layout(
    variant: Literal["body", "dual"],
) -> None:
    connected = await load_fixture(database(variant))
    async with connected.transaction() as transaction:
        rows = await transaction.fetch_all(
            sqlite.raw(
                "SELECT email, balance FROM users ORDER BY email",
                validate=AccountSummary,
            )
        )
    assert_type(rows, list[AccountSummary])
    assert_eq(
        rows,
        [
            AccountSummary(email="Ada", balance=12),
            AccountSummary(email="Grace", balance=12),
            AccountSummary(email="Linus", balance=5),
        ],
    )
