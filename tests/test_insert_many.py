"""Explicit batch destinations preserve native insert behavior."""

from decimal import Decimal
from typing import Any, ClassVar, assert_type

from snektest import Param, assert_eq, assert_is, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import initialized_database, provide_mariadb_server


@test(mark="medium")
async def sqlite_batch_returns_declared_rows() -> None:
    """The destination supplies the Row type for a native multi-row insert."""

    class Account[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.GenCol[int] = sqlite.Integer(
            primary_key=True, auto_increment=True, default=sqlite.PENDING_GENERATION
        )
        name: sqlite.Col[str] = sqlite.Text()

    async with (
        await initialized_database(database=":memory:", models=[Account]) as database,
        database.transaction() as transaction,
    ):
        accounts = await transaction.execute(
            sqlite.insert_many(
                Account, [Account(name="Ada"), Account(name="Grace")]
            ).returning()
        )

    assert_type(accounts, list[Account[sqlite.Row]])
    assert_eq(
        [(account.account_id, account.name) for account in accounts],
        [(1, "Ada"), (2, "Grace")],
    )
    for account in accounts:
        assert_is(type(account), Account)


@test(mark="slow")
async def mariadb_batch_persists_logical_values() -> None:
    """Explicit batches retain MariaDB's JSON and Decimal codecs."""
    server = await load_fixture(provide_mariadb_server())

    class Product[State = mariadb.Pending](mariadb.Model[State]):
        __row_type__: ClassVar[mariadb.ReadType[Product[mariadb.Row]]]
        product_id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
        price: mariadb.Col[Decimal] = mariadb.Decimal(precision=12, scale=2)
        payload: mariadb.JsonCol[dict[str, int]] = mariadb.Json()

    async with await initialized_database(
        server.config(), models=[Product]
    ) as database:
        async with database.transaction() as transaction:
            result = await transaction.execute(
                mariadb.insert_many(
                    Product,
                    [
                        Product(
                            product_id=1, price=Decimal("12.50"), payload={"answer": 42}
                        ),
                        Product(
                            product_id=2, price=Decimal("3.25"), payload={"answer": 9}
                        ),
                    ],
                )
            )
        async with database.transaction() as transaction:
            products = await transaction.fetch_all(
                mariadb.select(Product).all().order_by(Product.product_id.asc())
            )

    assert_type(result, None)
    assert_eq(
        [(product.price, product.payload) for product in products],
        [
            (Decimal("12.50"), {"answer": 42}),
            (Decimal("3.25"), {"answer": 9}),
        ],
    )


@test(mark="medium")
async def empty_sqlite_batch_returns_a_typed_empty_list() -> None:
    """The declared destination fixes empty-result typing without requiring a table."""

    class Account[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    async with (
        await sqlite.Database.initialize(database=":memory:") as database,
        database.transaction() as transaction,
    ):
        accounts = await transaction.execute(
            sqlite.insert_many(Account, []).returning()
        )

    assert_type(accounts, list[Account[sqlite.Row]])
    assert_eq(accounts, [])


@test(mark="medium")
async def empty_batch_cannot_cross_backends_after_erasure() -> None:
    """An explicit MariaDB destination remains MariaDB even with no rows."""

    class Product[State = mariadb.Pending](mariadb.Model[State]):
        __row_type__: ClassVar[mariadb.ReadType[Product[mariadb.Row]]]
        product_id: mariadb.Col[int] = mariadb.Integer(primary_key=True)

    query: Any = mariadb.insert_many(Product, [])

    async with (
        await sqlite.Database.initialize(database=":memory:") as database,
        database.transaction() as transaction,
    ):
        with assert_raises(sqlite.DatabaseRuntimeError):
            await transaction.execute(query)


@test(
    [Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")],
    [
        Param(kind, name=kind)
        for kind in (
            "wrong-model",
            "mixed-models",
            "row-state",
            "foreign-row",
            "foreign-empty",
            "instance",
            "pending-specialization",
            "row-specialization",
            "alias",
        )
    ],
    mark="fast",
)
def invalid_batch_inputs_are_rejected_after_erasure(backend: str, kind: str) -> None:
    """Runtime guards do not rely on surviving annotations or a nonempty batch."""

    class SqliteAccount[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[SqliteAccount[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    class SqliteOther[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[SqliteOther[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    class MariaAccount[State = mariadb.Pending](mariadb.Model[State]):
        __row_type__: ClassVar[mariadb.ReadType[MariaAccount[mariadb.Row]]]
        account_id: mariadb.Col[int] = mariadb.Integer(primary_key=True)

    class MariaOther[State = mariadb.Pending](mariadb.Model[State]):
        __row_type__: ClassVar[mariadb.ReadType[MariaOther[mariadb.Row]]]
        account_id: mariadb.Col[int] = mariadb.Integer(primary_key=True)

    namespace: Any = sqlite if backend == "sqlite" else mariadb
    model: Any = SqliteAccount if backend == "sqlite" else MariaAccount
    other: Any = SqliteOther if backend == "sqlite" else MariaOther
    foreign: Any = MariaAccount if backend == "sqlite" else SqliteAccount
    destinations: dict[str, Any] = {
        "foreign-empty": foreign,
        "instance": model(account_id=1),
        "pending-specialization": model[namespace.Pending],
        "row-specialization": model[namespace.Row],
        "alias": namespace.alias(model, object, name="another_account"),
    }
    rows: dict[str, list[Any]] = {
        "wrong-model": [other(account_id=1)],
        "mixed-models": [model(account_id=1), other(account_id=2)],
        "row-state": [namespace.complete(model, account_id=1)],
        "foreign-row": [foreign(account_id=1)],
    }

    with assert_raises(sqlite.QueryConstructionError):
        namespace.insert_many(destinations.get(kind, model), rows.get(kind, []))


@test(mark="fast")
def empty_batch_sql_inspection_has_no_statement() -> None:
    """A known destination does not turn a no-op into a fictitious INSERT."""

    class Account[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    with assert_raises(sqlite.QueryCompilationError):
        sqlite.insert_many(Account, []).compile()


@test(mark="slow")
async def mariadb_batch_returning_keeps_generated_ids() -> None:
    """MariaDB's existing INSERT RETURNING still materializes declared Row values."""
    server = await load_fixture(provide_mariadb_server())

    class Account[State = mariadb.Pending](mariadb.Model[State]):
        __row_type__: ClassVar[mariadb.ReadType[Account[mariadb.Row]]]
        account_id: mariadb.GenCol[int] = mariadb.Integer(
            primary_key=True, auto_increment=True, default=mariadb.PENDING_GENERATION
        )
        name: mariadb.Col[str] = mariadb.Text()

    async with (
        await initialized_database(server.config(), models=[Account]) as database,
        database.transaction() as transaction,
    ):
        accounts = await transaction.execute(
            mariadb.insert_many(
                Account, [Account(name="Ada"), Account(name="Grace")]
            ).returning()
        )

    assert_type(accounts, list[Account[mariadb.Row]])
    assert_eq(
        [(account.account_id, account.name) for account in accounts],
        [(1, "Ada"), (2, "Grace")],
    )
    for account in accounts:
        assert_is(type(account), Account)


@test(mark="medium")
async def sqlite_batch_conflict_uses_attempted_values() -> None:
    """Conflict updates reuse the native attempted-value handling."""

    class Settings[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Settings[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        digest_hour: sqlite.Col[int] = sqlite.Integer(default=9)

    async with await initialized_database(
        database=":memory:", models=[Settings]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(sqlite.insert(Settings(account_id=1, digest_hour=18)))
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.insert_many(
                    Settings,
                    [Settings(account_id=1, digest_hour=12), Settings(account_id=2)],
                ).on_conflict(
                    Settings.account_id,
                    action=sqlite.DoUpdate(Settings.digest_hour.to_inserted()),
                )
            )
        async with database.transaction() as transaction:
            settings = await transaction.fetch_all(
                sqlite.select(Settings).all().order_by(Settings.account_id.asc())
            )

    assert_eq(
        [(setting.account_id, setting.digest_hour) for setting in settings],
        [(1, 12), (2, 9)],
    )


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [Param(kind, name=kind) for kind in ("list", "tuple", "empty-list", "empty-tuple")],
    mark="fast",
)
def single_insert_rejects_sequences(backend: str, kind: str) -> None:
    """Even empty batches must name their destination through insert_many."""

    class Account[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    class MariaAccount[State = mariadb.Pending](mariadb.Model[State]):
        __row_type__: ClassVar[mariadb.ReadType[MariaAccount[mariadb.Row]]]
        account_id: mariadb.Col[int] = mariadb.Integer(primary_key=True)

    namespace: Any = sqlite if backend == "sqlite" else mariadb
    model: Any = Account if backend == "sqlite" else MariaAccount
    batches: dict[str, Any] = {
        "list": [model(account_id=1)],
        "tuple": (model(account_id=1),),
        "empty-list": [],
        "empty-tuple": (),
    }

    with assert_raises(namespace.QueryConstructionError):
        namespace.insert(batches[kind])
