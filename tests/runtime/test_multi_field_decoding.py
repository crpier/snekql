"""Multi-field results preserve decoder order and fail rather than truncate."""

from typing import Any, ClassVar, cast
from uuid import UUID

from pydantic import BaseModel, field_validator
from snektest import Param, assert_eq, assert_is, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.errors import ModelValidationError
from snekql.storage import StorageBackend
from tests.helpers import initialized_database
from tests.runtime.test_named_codecs import (
    DocumentResult,
    LocalDocument,
    MariaDocument,
    provide_mariadb_documents,
    provide_sqlite_documents,
)
from tests.runtime.test_projection_decoder import PolicyColumn


class OrderedColumn(PolicyColumn):
    """Record public policy effects; an SQL sentinel deliberately fails."""

    calls: ClassVar[list[tuple[str, object]]] = []

    def __decode_with_policy__(
        self, raw: object, *, backend: StorageBackend, validate: bool
    ) -> object:
        OrderedColumn.calls.append((cast("str", self.name), raw))
        if raw == -1:
            msg = "decoder stopped"
            raise StopIteration(msg)
        return super().__decode_with_policy__(raw, backend=backend, validate=validate)


class OrderedReading[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[OrderedReading[sqlite.Row]]]
    first: OrderedReading.Col[int] = cast(
        "Any", OrderedColumn(storage_class="INTEGER", storage_type_name="Integer")
    )
    second: OrderedReading.Col[int] = cast(
        "Any", OrderedColumn(storage_class="INTEGER", storage_type_name="Integer")
    )
    third: OrderedReading.Col[int] = cast(
        "Any", OrderedColumn(storage_class="INTEGER", storage_type_name="Integer")
    )


class OrderedResult(BaseModel):
    a: int
    b: int
    c: int

    @field_validator("c")
    @classmethod
    def final_contract(cls, value: int) -> int:
        return value + 1000


@test(
    [Param(mode, name=mode) for mode in ("buffered", "streamed", "one", "returning")],
    mark="medium",
)
async def multi_field_decoder_order_policy_and_stop_failure(mode: str) -> None:
    async with (
        await initialized_database(database=":memory:", models=[OrderedReading]) as db,
        db.transaction() as tx,
    ):
        await tx.execute(sqlite.insert(OrderedReading(first=1, second=2, third=3)))

        async def read(*, named: bool, validate: bool) -> Any:
            if mode == "returning":
                write = (
                    sqlite.update(OrderedReading).all().set(OrderedReading.first.to(1))
                )
                q: Any = (
                    write.returning_as(
                        OrderedResult,
                        a=OrderedReading.first,
                        b=OrderedReading.second,
                        c=OrderedReading.third,
                    )
                    if named
                    else write.returning(
                        OrderedReading.first,
                        OrderedReading.second,
                        OrderedReading.third,
                    )
                )
                return (await tx.execute(q, validate=validate))[0]
            q = (
                sqlite.select(OrderedReading).project(
                    OrderedResult,
                    a=OrderedReading.first,
                    b=OrderedReading.second,
                    c=OrderedReading.third,
                )
                if named
                else sqlite.select(
                    OrderedReading.first, OrderedReading.second, OrderedReading.third
                )
            )
            if mode == "buffered":
                return (await tx.fetch_all(q, validate=validate))[0]
            if mode == "one":
                return await tx.fetch_one(q, validate=validate)
            async with tx.fetch_chunks(q, size=1, validate=validate) as chunks:
                rows = [row async for chunk in chunks for row in chunk]
                return rows[0]

        for validate in (False, True, False):
            for named in (False, True):
                OrderedColumn.calls.clear()
                row = await read(named=named, validate=validate)
                assert_eq(
                    OrderedColumn.calls, [("first", 1), ("second", 2), ("third", 3)]
                )
                if named:
                    assert_is(type(row), OrderedResult)
                    assert_eq(
                        (row.a, row.b, row.c),
                        (101, 102, 1103) if validate else (201, 202, 1203),
                    )
                else:
                    assert_eq(row, (101, 102, 103) if validate else (201, 202, 203))

        await tx.execute(
            sqlite.update(OrderedReading).all().set(OrderedReading.second.to(-1))
        )
        for named in (False, True):
            OrderedColumn.calls.clear()
            with assert_raises(RuntimeError) as caught:
                await read(named=named, validate=True)
            assert_eq(str(caught.exception), "generator raised StopIteration")
            assert_is(type(caught.exception.__cause__), StopIteration)
            assert_eq(OrderedColumn.calls, [("first", 1), ("second", -1)])
            # Application decoding is outside the driver failure boundary.
            assert_eq(await tx.fetch_one(sqlite.select(OrderedReading.third)), 103)
        await tx.execute(
            sqlite.update(OrderedReading).all().set(OrderedReading.second.to(2))
        )
        assert_eq(await read(named=False, validate=True), (101, 102, 103))


class RejectOrdered(OrderedResult):
    @field_validator("c")
    @classmethod
    def reject_final_contract(cls, _value: int) -> int:
        msg = "named results must validate"
        raise ValueError(msg)


@test(mark="medium")
async def multi_field_named_failure_keeps_write_effects_and_transaction() -> None:
    async with (
        await initialized_database(database=":memory:", models=[OrderedReading]) as db,
        db.transaction() as tx,
    ):
        await tx.execute(sqlite.insert(OrderedReading(first=1, second=2, third=3)))
        OrderedColumn.calls.clear()
        with assert_raises(ModelValidationError):
            await tx.execute(
                sqlite.update(OrderedReading)
                .all()
                .set(OrderedReading.first.to(9))
                .returning_as(
                    RejectOrdered,
                    a=OrderedReading.first,
                    b=OrderedReading.second,
                    c=OrderedReading.third,
                )
            )
        assert_eq(OrderedColumn.calls, [("first", 9), ("second", 2), ("third", 3)])
        # Whole-model read observes stored values rather than projection hooks.
        row = await tx.fetch_one(sqlite.select(OrderedReading))
        assert_eq((row.first, row.second, row.third), (9, 2, 3))


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [Param(mode, name=mode) for mode in ("buffered", "streamed", "one", "returning")],
    mark="medium",
)
async def multi_field_collection_codecs_keep_position_and_final_shape(
    backend: str, mode: str
) -> None:
    api: Any = sqlite if backend == "sqlite" else mariadb
    model: Any = LocalDocument if backend == "sqlite" else MariaDocument
    db = await load_fixture(
        provide_sqlite_documents()
        if backend == "sqlite"
        else provide_mariadb_documents()
    )
    async with db.transaction() as tx:
        for named in (False, True):
            if mode == "returning":
                write = api.insert_many(
                    model, [model(id=UUID(int=2 + named), payload=[4, 5])]
                )
                query = (
                    write.returning_as(
                        DocumentResult, values=model.payload, key=model.id
                    )
                    if named
                    else write.returning(model.payload, model.id)
                )
                rows = await tx.execute(query)
                expected = (UUID(int=3 if named else 2), [4, 5])
            else:
                query = (
                    api.select(model).project(
                        DocumentResult, values=model.payload, key=model.id
                    )
                    if named
                    else api.select(model.payload, model.id)
                )
                if mode == "one":
                    rows = [await tx.fetch_one(query)]
                elif mode == "buffered":
                    rows = await tx.fetch_all(query)
                else:
                    async with tx.fetch_chunks(query, size=1) as chunks:
                        rows = [row async for chunk in chunks for row in chunk]
                expected = (UUID(int=1), [2, 3])
            assert_eq(len(rows), 1)
            if named:
                assert_is(type(rows[0]), DocumentResult)
                assert_eq((rows[0].key, rows[0].values), expected)
            else:
                assert_is(type(rows[0]), tuple)
                assert_eq(rows[0], (expected[1], expected[0]))
