"""Direct MariaDB JSON/Decimal descriptors through the actual native runtime."""

from collections.abc import AsyncGenerator
from decimal import Decimal
from pathlib import Path
from typing import assert_type

from anyio import to_thread
from snekql import mariadb as native
from snekql.testing.mariadb import TemporaryMariaDBServer, temporary_mariadb_server
from snektest import assert_eq, fixture, load_fixture, test

from scratchpad.dual_descriptors import mariadb
from scratchpad.dual_descriptors.maria_models import Product, ProductRow


@fixture(scope="session")
async def server() -> AsyncGenerator[TemporaryMariaDBServer]:
    async with temporary_mariadb_server(
        data_directory=Path(".git/dual-descriptors/mariadb"),
        socket_path=await to_thread.run_sync(
            Path(".git/dual-descriptors.sock").resolve
        ),
        transports={"unix_socket"},
        reset_database=True,
    ) as instance:
        yield instance


@fixture
async def database() -> AsyncGenerator[native.Database]:
    instance = await load_fixture(server())
    await instance.reset_database()
    async with await native.Database.initialize(instance.config()) as connected:
        await connected.migrate({"001": mariadb.scaffold(ProductRow)})
        async with connected.transaction() as transaction:
            await mariadb.Transaction(transaction).execute(
                mariadb.insert(
                    Product(identity=1, price=Decimal("12.50"), data={"answer": 42})
                )
            )
            await mariadb.Transaction(transaction).execute(
                mariadb.insert(Product(identity=2, price=Decimal("1.50"), data={}))
            )
        yield connected


@test(mark="slow")
async def inline_json_expression_retains_nullable_int() -> None:
    connected = await load_fixture(database())
    async with connected.transaction() as transaction:
        rows = await transaction.fetch_all(
            native.select(ProductRow.data.json_extract_int("$.answer"))
            .all()
            .order_by(ProductRow.identity.asc())
        )
    assert_type(rows, list[int | None])
    assert_eq(rows, [42, None])


@test(mark="slow")
async def inline_decimal_projection_retains_decimal() -> None:
    connected = await load_fixture(database())
    async with connected.transaction() as transaction:
        rows = await transaction.fetch_all(
            native.select(ProductRow.price).all().order_by(ProductRow.identity.asc())
        )
    assert_type(rows, list[Decimal])
    assert_eq(rows, [Decimal("12.50"), Decimal("1.50")])


@test(mark="slow")
async def aliased_json_descriptor_preserves_its_codec() -> None:
    connected = await load_fixture(database())

    class Role:
        pass

    source = native.alias(mariadb.table(ProductRow), Role, name="p")
    async with connected.transaction() as transaction:
        rows = await transaction.fetch_all(
            native.select(source.column(ProductRow.data))
            .all()
            .order_by(source.column(ProductRow.identity).asc())
            .for_update()
        )
    assert_type(rows, list[dict[str, int]])
    assert_eq(rows, [{"answer": 42}, {}])


@test(mark="slow")
async def native_model_result_is_still_not_a_public_dual_row() -> None:
    from snektest import assert_ne

    connected = await load_fixture(database())
    async with connected.transaction() as transaction:
        rows = await transaction.fetch_all(
            native.select(mariadb.table(ProductRow)).all()
        )
    assert_type(rows, list[ProductRow])
    assert_ne(type(rows[0]), ProductRow)


@test(mark="slow")
async def direct_decimal_foreign_key_keeps_precision() -> None:
    connected = await load_fixture(database())

    class Quote(mariadb.Model):
        __row__ = mariadb.paired(lambda: QuoteRow)
        price: mariadb.Col[Decimal] = mariadb.Decimal(12, 2, unique=True)

    class QuoteRow(Quote, mariadb.Row):
        table_name = "quotes"

    class Item(mariadb.Model):
        __row__ = mariadb.paired(lambda: ItemRow)
        price: mariadb.FKCol[QuoteRow, Decimal] = mariadb.ForeignKey(QuoteRow.price)

    class ItemRow(Item, mariadb.Row):
        table_name = "items"

    await connected.migrate(
        {"001": mariadb.scaffold(ProductRow), "002": mariadb.scaffold(ItemRow)}
    )
    async with connected.transaction() as transaction:
        await mariadb.Transaction(transaction).execute(
            mariadb.insert(Quote(price=Decimal("12.50")))
        )
        await mariadb.Transaction(transaction).execute(
            mariadb.insert(Item(price=Decimal("12.50")))
        )
    async with connected.transaction() as transaction:
        rows = await transaction.fetch_all(
            native.select(ItemRow.price)
            .join(mariadb.table(QuoteRow), on=ItemRow.price.references(QuoteRow.price))
            .all()
        )
    assert_type(rows, list[Decimal])
    assert_eq(rows, [Decimal("12.50")])
