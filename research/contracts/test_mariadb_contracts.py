"""The same runtime guarantees on real, isolated MariaDB servers."""

from collections.abc import AsyncGenerator
from typing import Any

from snektest import Param, assert_eq, fixture, load_fixture, test

from research.contracts.experiment import observe_mariadb


@fixture(scope="session")
async def observations() -> AsyncGenerator[dict[str, Any]]:
    """Collect once; tests only read the completed observations."""
    yield {
        "snekql": await observe_mariadb("snekql"),
        "sqlalchemy": await observe_mariadb("sqlalchemy"),
    }


@test(
    [
        Param(value="snekql", name="snekql"),
        Param(value="sqlalchemy", name="sqlalchemy"),
    ],
    mark="slow",
)
async def utc_instant_survives_a_new_transaction(library: str) -> None:
    """Readback must be an aware datetime normalized to millisecond UTC."""
    runs = await load_fixture(observations())
    recorded = runs[library]["application"]["offset"]
    assert_eq(
        (recorded["fetched"]["created_at"], recorded["fetched_types"]["created_at"]),
        ("2026-01-02 03:04:05.123000+00:00", "datetime"),
    )


@test(
    [
        Param(value="snekql", name="snekql"),
        Param(value="sqlalchemy", name="sqlalchemy"),
    ],
    mark="slow",
)
async def checked_quantity_rejects_external_zero(library: str) -> None:
    """Raw SQL cannot evade the installed positive-quantity constraint."""
    runs = await load_fixture(observations())
    assert_eq(runs[library]["raw"]["zero_quantity"]["outcome"], "rejected")


@test(
    [
        Param(value="snekql", name="snekql"),
        Param(value="sqlalchemy", name="sqlalchemy"),
    ],
    mark="slow",
)
async def maximum_cents_remain_an_integer(library: str) -> None:
    """The largest allowed amount must not overflow a 32-bit intermediate type."""
    runs = await load_fixture(observations())
    recorded = runs[library]["application"]["upper_bounds"]
    assert_eq(
        (recorded["fetched"]["price_cents"], recorded["fetched_types"]["price_cents"]),
        ("9999999999", "int"),
    )


@test(mark="slow")
async def snekql_literal_default_remains_intentional_drift() -> None:
    """MariaDB must expose the same unsupported expectation as SQLite."""
    runs = await load_fixture(observations())
    assert_eq(runs["snekql"]["verification"]["strict"], "rejected")


@test(mark="slow")
async def sqlalchemy_bulk_none_is_not_an_omission() -> None:
    """The custom timestamp type must see explicit None in bulk inserts too."""
    runs = await load_fixture(observations())
    assert_eq(runs["sqlalchemy"]["bulk"]["null_timestamp"]["outcome"], "rejected")
