"""Searched CASE evaluates and materializes on both supported backends."""

from typing import assert_type

from snektest import assert_eq, load_fixture, test

from snekql import mariadb, sqlite
from tests.query.test_arithmetic import Inventory
from tests.query.test_value_functions import Profile
from tests.runtime.test_arithmetic import (
    MariaInventory,
    provide_mariadb_inventory,
    provide_sqlite_inventory,
)
from tests.runtime.test_value_functions import (
    MariaProfile,
    provide_mariadb_profiles,
    provide_sqlite_profiles,
)


@test(mark="medium")
async def sqlite_case_unknown_condition_uses_fallback() -> None:
    """NULL equality is UNKNOWN, so it takes the explicit fallback branch."""
    database = await load_fixture(provide_sqlite_profiles())
    query = sqlite.select(
        sqlite.case(Profile.nickname.eq("Ada"), then="matched", otherwise="fallback")
    ).order_by(Profile.id.asc())

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[str])
    assert_eq(rows, ["fallback", "matched", "fallback"])


@test(mark="medium")
async def sqlite_case_nullable_branch_composes_with_functions() -> None:
    """CASE nullability feeds COALESCE and subsequent text functions."""
    database = await load_fixture(provide_sqlite_profiles())
    expression = sqlite.case(Profile.id.eq(2), then=Profile.nickname, otherwise=None)
    query = sqlite.select(expression.coalesce("missing").lower()).order_by(
        Profile.id.asc()
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[str])
    assert_eq(rows, ["missing", "ada", "missing"])


@test(mark="medium")
async def sqlite_case_assignment_uses_current_values() -> None:
    """A conditional assignment computes its chosen branch inside UPDATE."""
    database = await load_fixture(provide_sqlite_inventory())
    query = (
        sqlite.update(Inventory)
        .set(
            Inventory.quantity.to_expr(
                sqlite.case(
                    Inventory.quantity.gte_col(Inventory.version.add(2)),
                    then=Inventory.quantity.sub(1),
                    otherwise=Inventory.quantity,
                )
            )
        )
        .all()
    )

    async with database.transaction() as transaction:
        await transaction.execute(query)
    async with database.transaction() as transaction:
        quantity = await transaction.fetch_one(sqlite.select(Inventory.quantity))

    assert_eq(quantity, 2)


@test(mark="medium")
async def sqlite_case_literal_floats_keep_float_domain() -> None:
    """Float literal branches decode as floats without borrowing a column codec."""
    database = await load_fixture(provide_sqlite_profiles())
    query = sqlite.select(
        sqlite.case(Profile.id.eq(2), then=1.5, otherwise=2.5)
    ).order_by(Profile.id.asc())

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[float])
    assert_eq(rows, [2.5, 1.5, 2.5])


@test(mark="slow")
async def mariadb_case_unknown_condition_uses_fallback() -> None:
    """NULL equality is UNKNOWN, so it takes the explicit fallback branch."""
    database = await load_fixture(provide_mariadb_profiles())
    query = mariadb.select(
        mariadb.case(
            MariaProfile.nickname.eq("Ada"), then="matched", otherwise="fallback"
        )
    ).order_by(MariaProfile.id.asc())

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[str])
    assert_eq(rows, ["fallback", "matched", "fallback"])


@test(mark="slow")
async def mariadb_case_nullable_branch_composes_with_functions() -> None:
    """CASE nullability feeds COALESCE and subsequent text functions."""
    database = await load_fixture(provide_mariadb_profiles())
    expression = mariadb.case(
        MariaProfile.id.eq(2), then=MariaProfile.nickname, otherwise=None
    )
    query = mariadb.select(expression.coalesce("missing").lower()).order_by(
        MariaProfile.id.asc()
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[str])
    assert_eq(rows, ["missing", "ada", "missing"])


@test(mark="slow")
async def mariadb_case_assignment_uses_current_values() -> None:
    """A conditional assignment computes its chosen branch inside UPDATE."""
    database = await load_fixture(provide_mariadb_inventory())
    query = (
        mariadb.update(MariaInventory)
        .set(
            MariaInventory.quantity.to_expr(
                mariadb.case(
                    MariaInventory.quantity.gte_col(MariaInventory.version.add(2)),
                    then=MariaInventory.quantity.sub(1),
                    otherwise=MariaInventory.quantity,
                )
            )
        )
        .all()
    )

    async with database.transaction() as transaction:
        await transaction.execute(query)
    async with database.transaction() as transaction:
        quantity = await transaction.fetch_one(mariadb.select(MariaInventory.quantity))

    assert_eq(quantity, 2)


@test(mark="slow")
async def mariadb_case_literal_floats_keep_float_domain() -> None:
    """Float literal branches decode as floats without borrowing a column codec."""
    database = await load_fixture(provide_mariadb_profiles())
    query = mariadb.select(
        mariadb.case(MariaProfile.id.eq(2), then=1.5, otherwise=2.5)
    ).order_by(MariaProfile.id.asc())

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[float])
    assert_eq(rows, [2.5, 1.5, 2.5])


@test(mark="medium")
async def sqlite_case_normalizes_integer_literal_in_float_domain() -> None:
    """Python's accepted integer literal must not break a float result contract."""
    database = await load_fixture(provide_sqlite_profiles())
    query = sqlite.select(
        sqlite.case(Profile.id.eq(2), then=1, otherwise=2.5)
    ).order_by(Profile.id.asc())

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[float])
    assert_eq(rows, [2.5, 1.0, 2.5])


@test(mark="slow")
async def mariadb_case_normalizes_integer_literal_in_float_domain() -> None:
    """Python's accepted integer literal must not break a float result contract."""
    database = await load_fixture(provide_mariadb_profiles())
    query = mariadb.select(
        mariadb.case(MariaProfile.id.eq(2), then=1, otherwise=2.5)
    ).order_by(MariaProfile.id.asc())

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[float])
    assert_eq(rows, [2.5, 1.0, 2.5])
