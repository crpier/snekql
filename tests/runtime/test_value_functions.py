"""SQL value functions materialize through real backend transactions."""

from collections.abc import AsyncGenerator
from typing import assert_type

from snektest import assert_eq, fixture, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import provide_mariadb_server
from tests.query.test_arithmetic import NumericValues
from tests.query.test_value_functions import Profile
from tests.runtime.test_arithmetic import (
    MariaNumericValues,
    provide_mariadb_numeric_values,
    provide_sqlite_numeric_values,
)


class MariaProfile[S = mariadb.Pending](
    mariadb.Model[S, "MariaProfile[mariadb.Fetched]"]
):
    """Optional native text with a Unicode sample."""

    id: MariaProfile.Col[int] = mariadb.Integer(primary_key=True)
    nickname: MariaProfile.Col[str | None] = mariadb.Text(nullable=True)


@fixture
async def provide_sqlite_profiles() -> AsyncGenerator[sqlite.Database]:
    """Seed missing, ASCII, and multibyte text values."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001_profiles": sqlite.scaffold([Profile])})
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.insert(
                    [
                        Profile(id=1, nickname=None),
                        Profile(id=2, nickname="Ada"),
                        Profile(id=3, nickname="é界"),
                    ]
                )
            )
        yield database


@test(mark="medium")
async def sqlite_coalesce_removes_nullability() -> None:
    """A non-null fallback gives every row a string result."""
    database = await load_fixture(provide_sqlite_profiles())
    query = (
        sqlite.select(Profile.nickname.coalesce("anonymous").lower())
        .all()
        .order_by(Profile.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[str])
    assert_eq(rows, ["anonymous", "ada", "é界"])


@test(mark="medium")
async def sqlite_character_length_counts_characters() -> None:
    """Multibyte characters count once; missing text remains NULL."""
    database = await load_fixture(provide_sqlite_profiles())
    query = (
        sqlite.select(Profile.nickname.char_length()).all().order_by(Profile.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[int | None])
    assert_eq(rows, [None, 3, 2])


@test(mark="medium")
async def sqlite_text_assignment_evaluates_in_database() -> None:
    """Text expressions can replace missing stored values atomically."""
    database = await load_fixture(provide_sqlite_profiles())
    query = (
        sqlite.update(Profile)
        .set(Profile.nickname.to_expr(Profile.nickname.coalesce("anonymous").lower()))
        .all()
    )

    async with database.transaction() as transaction:
        await transaction.execute(query)
    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            sqlite.select(Profile.nickname).all().order_by(Profile.id.asc())
        )

    assert_eq(rows, ["anonymous", "ada", "é界"])


@fixture
async def provide_mariadb_profiles() -> AsyncGenerator[mariadb.Database]:
    """Seed missing, ASCII, and multibyte text values."""
    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001_profiles": mariadb.scaffold([MariaProfile])})
        async with database.transaction() as transaction:
            await transaction.execute(
                mariadb.insert(
                    [
                        MariaProfile(id=1, nickname=None),
                        MariaProfile(id=2, nickname="Ada"),
                        MariaProfile(id=3, nickname="é界"),
                    ]
                )
            )
        yield database


@test(mark="slow")
async def mariadb_coalesce_removes_nullability() -> None:
    """A non-null fallback gives every row a string result."""
    database = await load_fixture(provide_mariadb_profiles())
    query = (
        mariadb.select(MariaProfile.nickname.coalesce("anonymous").lower())
        .all()
        .order_by(MariaProfile.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[str])
    assert_eq(rows, ["anonymous", "ada", "é界"])


@test(mark="slow")
async def mariadb_character_length_counts_characters() -> None:
    """Multibyte characters count once; missing text remains NULL."""
    database = await load_fixture(provide_mariadb_profiles())
    query = (
        mariadb.select(MariaProfile.nickname.char_length())
        .all()
        .order_by(MariaProfile.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[int | None])
    assert_eq(rows, [None, 3, 2])


@test(mark="slow")
async def mariadb_text_assignment_evaluates_in_database() -> None:
    """Text expressions can replace missing stored values atomically."""
    database = await load_fixture(provide_mariadb_profiles())
    query = (
        mariadb.update(MariaProfile)
        .set(
            MariaProfile.nickname.to_expr(
                MariaProfile.nickname.coalesce("anonymous").lower()
            )
        )
        .all()
    )

    async with database.transaction() as transaction:
        await transaction.execute(query)
    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            mariadb.select(MariaProfile.nickname).all().order_by(MariaProfile.id.asc())
        )

    assert_eq(rows, ["anonymous", "ada", "é界"])


@test(mark="medium")
async def sqlite_floating_coalesce_normalizes_integer_fallback() -> None:
    """A float result must stay a float even when the bound fallback is an int."""
    database = await load_fixture(provide_sqlite_numeric_values())
    query = (
        sqlite.select(NumericValues.optional_real.coalesce(1))
        .all()
        .order_by(NumericValues.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[float])
    assert_eq(rows, [1.0, 1.5])


@test(mark="slow")
async def mariadb_floating_coalesce_normalizes_integer_fallback() -> None:
    """A float result must stay a float even when the bound fallback is an int."""
    database = await load_fixture(provide_mariadb_numeric_values())
    query = (
        mariadb.select(MariaNumericValues.optional_real.coalesce(1))
        .all()
        .order_by(MariaNumericValues.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[float])
    assert_eq(rows, [1.0, 1.5])


@test(mark="medium")
async def sqlite_nullable_fallback_preserves_missing_values() -> None:
    """COALESCE with only nullable operands may still produce SQL NULL."""
    database = await load_fixture(provide_sqlite_profiles())
    query = (
        sqlite.select(Profile.nickname.coalesce(None)).all().order_by(Profile.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[str | None])
    assert_eq(rows, [None, "Ada", "é界"])


@test(mark="medium")
async def sqlite_function_results_compose_with_numeric_operations() -> None:
    """A non-null integer fallback can feed further numeric operations."""
    database = await load_fixture(provide_sqlite_profiles())
    query = (
        sqlite.select(Profile.nickname.char_length().coalesce(0).mul(2))
        .all()
        .order_by(Profile.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[int])
    assert_eq(rows, [0, 6, 4])


@test(mark="slow")
async def mariadb_nullable_fallback_preserves_missing_values() -> None:
    """COALESCE with only nullable operands may still produce SQL NULL."""
    database = await load_fixture(provide_mariadb_profiles())
    query = (
        mariadb.select(MariaProfile.nickname.coalesce(None))
        .all()
        .order_by(MariaProfile.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[str | None])
    assert_eq(rows, [None, "Ada", "é界"])


@test(mark="slow")
async def mariadb_function_results_compose_with_numeric_operations() -> None:
    """A non-null integer fallback can feed further numeric operations."""
    database = await load_fixture(provide_mariadb_profiles())
    query = (
        mariadb.select(MariaProfile.nickname.char_length().coalesce(0).mul(2))
        .all()
        .order_by(MariaProfile.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[int])
    assert_eq(rows, [0, 6, 4])
