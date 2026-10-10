"""Derived SQL values retain source codecs without intermediate validators."""

from collections.abc import AsyncGenerator
from typing import Annotated, ClassVar, assert_type

from pydantic import AfterValidator, BaseModel, field_validator
from snektest import Param, assert_eq, fixture, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import provide_mariadb_server
from tests.query.test_ctes import ActiveRole, FilteredRole


def add_ten(value: int) -> int:
    """Expose whether source validation is applied exactly once during decoding."""
    return value + 10


class LocalNumber[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[LocalNumber[sqlite.Row]]]
    value: sqlite.Col[Annotated[int, AfterValidator(add_ten)]] = sqlite.Integer()


class NativeNumber[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[NativeNumber[mariadb.Row]]]
    value: mariadb.Col[Annotated[int, AfterValidator(add_ten)]] = mariadb.Integer()


class ScalarRole:
    """Keep the scalar's SQL source distinct from its containing SELECT."""


class Intermediate(BaseModel):
    """The SQL definition must not execute this application's transformation."""

    value: int | None

    @field_validator("value")
    @classmethod
    def add_thousand(cls, value: int | None) -> int | None:
        return None if value is None else value + 1000


class FinalNumber(BaseModel):
    """Only the final result contract runs after the source codec."""

    value: int | None

    @field_validator("value")
    @classmethod
    def add_hundred(cls, value: int | None) -> int | None:
        return None if value is None else value + 100


@fixture
async def provide_local_number() -> AsyncGenerator[sqlite.Database]:
    """Pending validation changes 1 to 11 before it is stored."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001_numbers": sqlite.scaffold([LocalNumber])})
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(LocalNumber(value=1)))
        yield database


@fixture
async def provide_native_number() -> AsyncGenerator[mariadb.Database]:
    """Use the same source-validator contract through the native driver."""
    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001_numbers": mariadb.scaffold([NativeNumber])})
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(NativeNumber(value=1)))
        yield database


@test(
    [Param("validated", name="validated"), Param("unchecked", name="unchecked")],
    [Param("buffered", name="buffered"), Param("streamed", name="streamed")],
    [Param("present", name="present"), Param("empty", name="empty")],
    mark="medium",
)
async def sqlite_nested_union_applies_only_final_result_validation(
    validation: str,
    consumption: str,
    scalar_match: str,
) -> None:
    """Scalar, alias and UNION references retain source validation policy."""
    database = await load_fixture(provide_local_number())
    token = LocalNumber.value.label("value")
    first = (
        sqlite.select(LocalNumber)
        .project(Intermediate, value=token)
        .cte(ActiveRole, name="first_number")
    )
    scalar_source = sqlite.alias(first, ScalarRole, name="scalar_number")
    rebound = sqlite.scalar(
        sqlite.select(scalar_source.column(token)).where(
            scalar_source.column(token).gt(0 if scalar_match == "present" else 100)
        )
    ).label("value")
    nested = (
        sqlite.select(first)
        .project(Intermediate, value=rebound)
        .cte(FilteredRole, name="nested_number")
    )
    peer = sqlite.alias(nested, ActiveRole, name="peer")
    operand = sqlite.select(peer).project(FinalNumber, value=peer.column(rebound))
    query = operand.union_all(operand)

    async with database.transaction() as transaction:
        if validation == "validated":
            if consumption == "streamed":
                async with transaction.fetch_chunks(query, size=1) as stream:
                    typed_rows = [row async for chunk in stream for row in chunk]
            else:
                typed_rows = await transaction.fetch_all(query)
            assert_type(typed_rows, list[FinalNumber])
            rows = typed_rows
        elif consumption == "streamed":
            async with transaction.fetch_chunks(
                query, size=1, validate=False
            ) as stream:
                rows = [row async for chunk in stream for row in chunk]
        else:
            rows = await transaction.fetch_all(query, validate=False)

    decoded_values: list[int | None] = []
    for row in rows:
        assert isinstance(row, FinalNumber)
        decoded_values.append(row.value)
    assert_eq(
        decoded_values,
        [None, None]
        if scalar_match == "empty"
        else [121, 121]
        if validation == "validated"
        else [111, 111],
    )


@test(
    [Param("validated", name="validated"), Param("unchecked", name="unchecked")],
    [Param("buffered", name="buffered"), Param("streamed", name="streamed")],
    [Param("present", name="present"), Param("empty", name="empty")],
    mark="slow",
)
async def mariadb_nested_union_applies_only_final_result_validation(
    validation: str,
    consumption: str,
    scalar_match: str,
) -> None:
    """Native derived values skip intermediate Python result transformations."""
    database = await load_fixture(provide_native_number())
    token = NativeNumber.value.label("value")
    first = (
        mariadb.select(NativeNumber)
        .project(Intermediate, value=token)
        .cte(ActiveRole, name="first_number")
    )
    scalar_source = mariadb.alias(first, ScalarRole, name="scalar_number")
    rebound = mariadb.scalar(
        mariadb.select(scalar_source.column(token)).where(
            scalar_source.column(token).gt(0 if scalar_match == "present" else 100)
        )
    ).label("value")
    nested = (
        mariadb.select(first)
        .project(Intermediate, value=rebound)
        .cte(FilteredRole, name="nested_number")
    )
    peer = mariadb.alias(nested, ActiveRole, name="peer")
    operand = mariadb.select(peer).project(FinalNumber, value=peer.column(rebound))
    query = operand.union_all(operand)

    async with database.transaction() as transaction:
        if validation == "validated":
            if consumption == "streamed":
                async with transaction.fetch_chunks(query, size=1) as stream:
                    typed_rows = [row async for chunk in stream for row in chunk]
            else:
                typed_rows = await transaction.fetch_all(query)
            assert_type(typed_rows, list[FinalNumber])
            rows = typed_rows
        elif consumption == "streamed":
            async with transaction.fetch_chunks(
                query, size=1, validate=False
            ) as stream:
                rows = [row async for chunk in stream for row in chunk]
        else:
            rows = await transaction.fetch_all(query, validate=False)

    decoded_values: list[int | None] = []
    for row in rows:
        assert isinstance(row, FinalNumber)
        decoded_values.append(row.value)
    assert_eq(
        decoded_values,
        [None, None]
        if scalar_match == "empty"
        else [121, 121]
        if validation == "validated"
        else [111, 111],
    )
