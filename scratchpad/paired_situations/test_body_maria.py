"""Real MariaDB observations for the body review file."""

from collections.abc import AsyncGenerator
from datetime import timedelta
from decimal import Decimal
from typing import assert_type
from uuid import UUID

from snekql import mariadb as native
from snektest import assert_eq, fixture, load_fixture, test

from scratchpad.paired_situations import body as app
from scratchpad.paired_situations.fixtures import server


@fixture
async def database() -> AsyncGenerator[native.Database]:
    instance = await load_fixture(server())
    await instance.reset_database()
    async with await native.Database.initialize(instance.config()) as connected:
        await connected.migrate({"001": native.scaffold([app.Product])})
        yield connected


@fixture
async def seeded_database() -> AsyncGenerator[native.Database]:
    async with database() as connected:
        async with connected.transaction() as raw:
            await app.create_product(raw)
        yield connected


@test(mark="slow")
async def product_insert_returns_precise_complete_contract() -> None:
    connected = await load_fixture(database())
    async with connected.transaction() as raw:
        product = await app.create_product(raw)
    assert_type(product, app.Product[native.Fetched])
    assert_eq((product.product_id, product.price), (1, Decimal("12.50")))


@test(mark="slow")
async def product_select_decodes_native_values() -> None:
    connected = await load_fixture(seeded_database())
    async with connected.transaction() as raw:
        products = await raw.fetch_all(app.mariadb.select(app.Product).all())
    assert_type(products, list[app.Product[native.Fetched]])
    assert_eq(
        (
            products[0].token,
            products[0].payload,
            products[0].active,
            products[0].image,
            products[0].description,
        ),
        (UUID(int=7), {"answer": 42}, True, b"image", "long description"),
    )


@test(mark="slow")
async def database_supplies_a_utc_datetime() -> None:
    connected = await load_fixture(seeded_database())
    async with connected.transaction() as raw:
        products = await raw.fetch_all(app.mariadb.select(app.Product).all())
    assert_eq(products[0].created_at.utcoffset(), timedelta(0))


@test(mark="slow")
async def json_expression_retains_nullable_integer_result() -> None:
    connected = await load_fixture(seeded_database())
    async with connected.transaction() as raw:
        answers = await app.product_answers(raw)
    assert_type(answers, list[int | None])
    assert_eq(answers, [42])
