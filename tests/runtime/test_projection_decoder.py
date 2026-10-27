"""Projection optimizations retain column extension and validation contracts."""

from typing import Annotated, Any, ClassVar, cast

from annotated_types import Ge
from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite
from snekql._dialect_expr import CompileCtx
from snekql.errors import ModelValidationError
from snekql.storage import Attr, StorageBackend
from tests.helpers import initialized_database


class DialectColumn(Attr[Any, Any, Any, Any, Any]):
    """A column that also implements the open-AST projection seam."""

    def __owner_model__(self) -> type[sqlite.Model[Any]]:
        return cast("type[sqlite.Model[Any]]", self.owner)

    def __compile_sql__(self, ctx: CompileCtx) -> tuple[str, tuple[object, ...]]:
        return ctx.render_column(self), ()

    def __compile_select_sql__(self, ctx: CompileCtx) -> tuple[str, tuple[object, ...]]:
        return self.__compile_sql__(ctx)

    def __decode__(self, raw: object) -> int:
        return cast("int", raw) + 300


class PolicyColumn(DialectColumn):
    """A column extension whose projection policy differs from its base codec."""

    def __decode_with_policy__(
        self, raw: object, *, backend: StorageBackend, validate: bool
    ) -> object:
        value = cast("int", self.decode(raw, backend=backend, validate=validate))
        return value + (100 if validate else 200)


class PolicyReading[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[PolicyReading[sqlite.Row]]]

    value: PolicyReading.Col[int] = cast(
        "Any", PolicyColumn(storage_class="INTEGER", storage_type_name="Integer")
    )


@test(
    [Param(value=method, name=method) for method in ("fetch_all", "fetch_chunks")],
    [Param(value=mode, name=mode) for mode in ("validated", "unchecked")],
    mark="medium",
)
async def column_extension_keeps_projection_policy(method: str, mode: str) -> None:
    """A column's policy seam takes precedence over its ordinary column codec."""
    validate = mode == "validated"
    async with (
        await initialized_database(
            database=":memory:", models=[PolicyReading]
        ) as database,
        database.transaction() as transaction,
    ):
        await transaction.execute(
            sqlite.raw("INSERT INTO policy_reading (value) VALUES (7), (8)")
        )
        query = sqlite.select(PolicyReading.value).order_by(PolicyReading.value.asc())
        if method == "fetch_all":
            values = await transaction.fetch_all(query, validate=validate)
        else:
            async with transaction.fetch_chunks(
                query, size=1, validate=validate
            ) as chunks:
                values = [value async for chunk in chunks for value in chunk]
    assert_eq(values, [107, 108] if validate else [207, 208])


class DialectReading[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[DialectReading[sqlite.Row]]]

    value: DialectReading.Col[int] = cast(
        "Any", DialectColumn(storage_class="INTEGER", storage_type_name="Integer")
    )


@test(
    [Param(value=method, name=method) for method in ("fetch_all", "fetch_chunks")],
    mark="medium",
)
async def column_extension_keeps_dialect_decoder(method: str) -> None:
    """The dialect projection decoder wins over an Attr subclass's base codec."""
    async with (
        await initialized_database(
            database=":memory:", models=[DialectReading]
        ) as database,
        database.transaction() as transaction,
    ):
        await transaction.execute(
            sqlite.raw("INSERT INTO dialect_reading (value) VALUES (7), (8)")
        )
        query = sqlite.select(DialectReading.value).order_by(DialectReading.value.asc())
        if method == "fetch_all":
            values = await transaction.fetch_all(query)
        else:
            async with transaction.fetch_chunks(query, size=1) as chunks:
                values = [value async for chunk in chunks for value in chunk]
    assert_eq(values, [307, 308])


@test(mark="medium")
async def returning_keeps_column_extension_policy() -> None:
    """Write projections share read dispatch precedence and execution policy."""
    async with (
        await initialized_database(
            database=":memory:", models=[PolicyReading]
        ) as database,
        database.transaction() as transaction,
    ):
        query = sqlite.insert(PolicyReading(value=7)).returning(PolicyReading.value)
        validated = await transaction.execute(query)
        unchecked = await transaction.execute(query, validate=False)
    assert_eq((validated, unchecked), (107, 207))


class Reading[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Reading[sqlite.Row]]]

    value: Reading.Col[Annotated[int, Ge(0)]] = sqlite.Text()


@test(
    [Param(value=method, name=method) for method in ("fetch_all", "fetch_chunks")],
    mark="medium",
)
async def reused_projection_keeps_each_executions_validation(method: str) -> None:
    """Unchecked execution cannot disable the next execution's column validation."""
    async with (
        await initialized_database(database=":memory:", models=[Reading]) as database,
        database.transaction() as transaction,
    ):
        await transaction.execute(
            sqlite.raw("INSERT INTO reading (value) VALUES ('-1')")
        )
        query = sqlite.select(Reading.value)

        async def read(*, validate: bool) -> object:
            if method == "fetch_all":
                return await transaction.fetch_all(query, validate=validate)
            async with transaction.fetch_chunks(
                query, size=1, validate=validate
            ) as chunks:
                return [value async for chunk in chunks for value in chunk]

        assert_eq(await read(validate=False), ["-1"])
        with assert_raises(ModelValidationError):
            await read(validate=True)
        assert_eq(await read(validate=False), ["-1"])


@test(mark="medium")
async def bulk_returning_keeps_each_executions_validation() -> None:
    """Each RETURNING batch gets its own policy without changing its shape."""
    async with (
        await initialized_database(database=":memory:", models=[Reading]) as database,
        database.transaction() as transaction,
    ):
        query = sqlite.insert_many(
            Reading, [Reading(value=7), Reading(value=8)]
        ).returning(Reading.value)
        unchecked = await transaction.execute(query, validate=False)
        validated = await transaction.execute(query)
        unchecked_again = await transaction.execute(query, validate=False)
    assert_eq((unchecked, validated, unchecked_again), (["7", "8"], [7, 8], ["7", "8"]))
