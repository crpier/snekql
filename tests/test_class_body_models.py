"""Public class-body declarations and model lifecycle behavior."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any, ClassVar, assert_type

from pydantic import Json
from snektest import (
    Param,
    assert_eq,
    assert_is,
    assert_raises,
    assert_true,
    load_fixture,
    test,
)

from snekql import mariadb, sqlite
from tests.helpers import initialized_database, provide_mariadb_server


@test(mark="fast")
def sqlite_class_body_constructs_pending_input() -> None:
    """The class-body row declaration replaces the second Model parameter."""

    class Account[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        email: sqlite.Col[str] = sqlite.Text()

    account = Account(email="ada@example.com")

    assert_type(account, Account[sqlite.Pending])
    assert_eq(account.email, "ada@example.com")


@test(mark="fast")
def row_constructor_is_rejected_after_callable_erasure() -> None:
    """A callable annotation must not make incomplete Row construction possible."""

    class Account[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.GenCol[int] = sqlite.Integer(
            primary_key=True, auto_increment=True, default=sqlite.PENDING_GENERATION
        )
        email: sqlite.Col[str] = sqlite.Text()

    def make(factory: Callable[..., Account[sqlite.Row]]) -> Account[sqlite.Row]:
        return factory(email="ada@example.com")

    with assert_raises(sqlite.ModelValidationError):
        make(Account[sqlite.Row])


@test(mark="fast")
def complete_creates_a_validated_row() -> None:
    """A snapshot has the declared Row type without an insert or a select."""

    class Account[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.GenCol[int] = sqlite.Integer(
            primary_key=True, auto_increment=True, default=sqlite.PENDING_GENERATION
        )
        email: sqlite.Col[str] = sqlite.Text()

    account = sqlite.complete(Account, account_id=7, email="ada@example.com")

    assert_type(account, Account[sqlite.Row])
    assert_eq(repr(account), "Account[Row](account_id=7, email='ada@example.com')")


@test(mark="fast")
def mariadb_complete_preserves_logical_values() -> None:
    """Decimal and JSON snapshots are logical values, not database wire values."""

    class Product[State = mariadb.Pending](mariadb.Model[State]):
        __row_type__: ClassVar[mariadb.ReadType[Product[mariadb.Row]]]
        price: mariadb.Col[Decimal] = mariadb.Decimal(precision=12, scale=2)
        payload: mariadb.JsonCol[dict[str, int]] = mariadb.Json()

    product = mariadb.complete(Product, price=Decimal("12.50"), payload={"answer": 42})

    assert_type(product, Product[mariadb.Row])
    assert_eq((product.price, product.payload), (Decimal("12.50"), {"answer": 42}))


@test(mark="fast")
def is_complete_distinguishes_rows_from_populated_pending_values() -> None:
    """Supplying a generated value does not change Pending into Row."""

    class Account[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.GenCol[int] = sqlite.Integer(
            primary_key=True, auto_increment=True, default=sqlite.PENDING_GENERATION
        )

    def identity(account: Account[sqlite.Pending] | Account[sqlite.Row]) -> int | None:
        if sqlite.is_complete(account):
            assert_type(account, Account[sqlite.Row])
            return account.account_id
        return None

    pending = Account(account_id=7)
    snapshot = sqlite.complete(Account, account_id=7)

    assert_eq((identity(pending), identity(snapshot)), (None, 7))


@test(mark="fast")
def declared_row_type_cannot_bypass_constructor_guard() -> None:
    """The declared Row type is an annotation, not a back door into construction."""

    class Account[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        email: sqlite.Col[str] = sqlite.Text()

    def make(factory: Callable[..., Account[sqlite.Row]]) -> Account[sqlite.Row]:
        return factory(email="Ada")

    with assert_raises(sqlite.ModelValidationError):
        make(Account.__row_type__())


@test(mark="fast")
def missing_row_declaration_is_rejected() -> None:
    """There is no inherited Any result when a declaration omits its Row type."""
    with assert_raises(sqlite.ModelDeclarationError):

        class Missing[State = sqlite.Pending](sqlite.Model[State]):
            email: sqlite.Col[str] = sqlite.Text()


@test(mark="fast")
def unrelated_row_declaration_is_rejected() -> None:
    """A model cannot promise another declaration's rows."""

    class Account[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        email: sqlite.Col[str] = sqlite.Text()

    with assert_raises(sqlite.ModelDeclarationError):

        class Wrong[State = sqlite.Pending](sqlite.Model[State]):
            __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
            email: sqlite.Col[str] = sqlite.Text()


@test(
    [
        Param({"account_id": 7}, name="missing-defaulted-field"),
        Param({"account_id": 7, "email": "Ada", "extra": 0}, name="unknown-field"),
        Param({"account_id": 7, "email": 42}, name="invalid-logical-value"),
        Param(
            {"account_id": sqlite.PENDING_GENERATION, "email": "Ada"},
            name="unavailable-id",
        ),
    ],
    mark="fast",
)
def complete_rejects_invalid_fields(values: dict[str, object]) -> None:
    """Keyword validation uses the declared fields even when typing cannot check them."""

    class Account[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.GenCol[int] = sqlite.Integer(
            primary_key=True, auto_increment=True, default=sqlite.PENDING_GENERATION
        )
        email: sqlite.Col[str] = sqlite.Text(default="Ada")

    with assert_raises(sqlite.ModelValidationError):
        sqlite.complete(Account, **values)


@test(mark="fast")
def complete_sqlite_json_accepts_logical_values() -> None:
    """Complete snapshots do not try to decode already-decoded JSON."""

    class Document[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Document[sqlite.Row]]]
        payload: sqlite.Col[Json[dict[str, int]]] = sqlite.Text()

    document = sqlite.complete(Document, payload={"answer": 42})

    assert_type(document, Document[sqlite.Row])
    assert_eq(document.payload, {"answer": 42})


@test(mark="fast")
def complete_rows_cannot_be_inserted_after_erasure() -> None:
    """The Row state is checked before building an insert, not only by ty."""

    class Account[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        email: sqlite.Col[str] = sqlite.Text()

    account: Any = sqlite.complete(Account, email="Ada")

    with assert_raises(sqlite.QueryConstructionError):
        sqlite.insert(account)


@test(mark="fast")
def complete_rejects_another_backend_after_erasure() -> None:
    """A namespace's construction helper still belongs to that backend."""

    class Account[State = mariadb.Pending](mariadb.Model[State]):
        __row_type__: ClassVar[mariadb.ReadType[Account[mariadb.Row]]]
        email: mariadb.Col[str] = mariadb.Text()

    model: Any = Account

    with assert_raises(sqlite.ModelValidationError):
        sqlite.complete(model, email="Ada")


@test(mark="fast")
def complete_rows_are_frozen() -> None:
    """Validated snapshots follow the same assignment rules as fetched rows."""

    class Account[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        email: sqlite.Col[str] = sqlite.Text()

    account: Any = sqlite.complete(Account, email="Ada")

    with assert_raises(sqlite.FrozenModelError):
        account.email = "Grace"


@test(mark="medium")
async def sqlite_insert_returning_materializes_the_declared_row() -> None:
    """INSERT RETURNING produces the public class and a real generated identifier."""

    class Account[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.GenCol[int] = sqlite.Integer(
            primary_key=True, auto_increment=True, default=sqlite.PENDING_GENERATION
        )
        email: sqlite.Col[str] = sqlite.Text()

    async with (
        await initialized_database(database=":memory:", models=[Account]) as database,
        database.transaction() as transaction,
    ):
        account = await transaction.execute(
            sqlite.insert(Account(email="Ada")).returning()
        )

    assert_type(account, Account[sqlite.Row])
    assert_is(type(account), Account)
    assert_eq(account.account_id, 1)
    assert_true(sqlite.is_complete(account))


@test(mark="slow")
async def mariadb_select_materializes_the_declared_row() -> None:
    """SELECT uses native Decimal and JSON decoding before recording Row state."""
    server = await load_fixture(provide_mariadb_server())

    class Product[State = mariadb.Pending](mariadb.Model[State]):
        __row_type__: ClassVar[mariadb.ReadType[Product[mariadb.Row]]]
        product_id: mariadb.GenCol[int] = mariadb.Integer(
            primary_key=True, auto_increment=True, default=mariadb.PENDING_GENERATION
        )
        price: mariadb.Col[Decimal] = mariadb.Decimal(precision=12, scale=2)
        payload: mariadb.JsonCol[dict[str, int]] = mariadb.Json()

    async with await initialized_database(
        server.config(), models=[Product]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(
                mariadb.insert(Product(price=Decimal("12.50"), payload={"answer": 42}))
            )
        async with database.transaction() as transaction:
            product = await transaction.fetch_one(mariadb.select(Product))

    assert_type(product, Product[mariadb.Row])
    assert_is(type(product), Product)
    assert_eq(
        (product.product_id, product.price, product.payload),
        (1, Decimal("12.50"), {"answer": 42}),
    )
    assert_true(mariadb.is_complete(product))


@test([Param("Pending", name="pending"), Param("Row", name="row")], mark="fast")
def sqlite_freezing_leaves_nested_json_mutable(
    state: str,
) -> None:
    """Frozen model fields do not recursively freeze JSON containers."""

    class Account[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        counters: sqlite.Col[Json[dict[str, int]]] = sqlite.Text()

    account = (
        sqlite.complete(Account, counters={"visits": 1})
        if state == "Row"
        else Account(counters={"visits": 1})
    )

    account.counters["visits"] = 2

    assert_type(account.counters, dict[str, int])
    assert_eq(account.counters, {"visits": 2})


@test([Param("Pending", name="pending"), Param("Row", name="row")], mark="fast")
def mariadb_freezing_leaves_nested_json_mutable(
    state: str,
) -> None:
    """MariaDB JsonCol has the same shallow freezing contract."""

    class Account[State = mariadb.Pending](mariadb.Model[State]):
        __row_type__: ClassVar[mariadb.ReadType[Account[mariadb.Row]]]
        counters: mariadb.JsonCol[dict[str, int]] = mariadb.Json()

    account = (
        mariadb.complete(Account, counters={"visits": 1})
        if state == "Row"
        else Account(counters={"visits": 1})
    )

    account.counters["visits"] = 2

    assert_type(account.counters, dict[str, int])
    assert_eq(account.counters, {"visits": 2})
