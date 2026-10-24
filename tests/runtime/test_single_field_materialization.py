"""One projected SQL field can decode to a collection or a named contract."""

from typing import Any

from pydantic import BaseModel, field_validator
from snektest import Param, assert_eq, assert_is, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.errors import FrozenModelError, ModelValidationError
from tests.helpers import initialized_database
from tests.runtime.test_joined_row_shape import Anchor, Payload
from tests.runtime.test_named_codecs import (
    LocalDocument,
    MariaDocument,
    provide_mariadb_documents,
    provide_sqlite_documents,
)
from tests.runtime.test_projection_decoder import PolicyReading


class OneCollection(BaseModel):
    values: list[int]

    @field_validator("values")
    @classmethod
    def final_contract_transforms_once(cls, value: list[int]) -> list[int]:
        return [*value, 99]


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [Param(mode, name=mode) for mode in ("buffered", "streamed", "one")],
    mark="medium",
)
async def one_field_keeps_decoded_collection_and_named_contract(
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
            query = (
                api.select(model).project(OneCollection, values=model.payload)
                if named
                else api.select(model.payload)
            )
            if mode == "one":
                rows = [await tx.fetch_one(query)]
            elif mode == "buffered":
                rows = await tx.fetch_all(query)
            else:
                async with tx.fetch_chunks(query, size=2) as chunks:
                    rows = [row async for chunk in chunks for row in chunk]
            if named:
                assert_is(type(rows[0]), OneCollection)
                assert_eq([row.values for row in rows], [[2, 3, 99]])
            else:
                assert_eq(rows, [[2, 3]])
                assert_is(type(rows[0]), list)


class OnePolicy(BaseModel):
    value: int | None

    @field_validator("value")
    @classmethod
    def transform_nonnull(cls, value: int | None) -> int | None:
        return None if value is None else value + 1000


class RejectPolicy(BaseModel):
    value: int

    @field_validator("value")
    @classmethod
    def reject_value(cls, _value: int) -> int:
        msg = "named contract must not be bypassed"
        raise ValueError(msg)


@test([Param(mode, name=mode) for mode in ("buffered", "streamed")], mark="medium")
async def one_field_retains_hooks_nulls_errors_and_whole_model_shape(mode: str) -> None:
    async with (
        await initialized_database(
            database=":memory:", models=[PolicyReading, Anchor, Payload]
        ) as db,
        db.transaction() as tx,
    ):
        await tx.execute(sqlite.insert(PolicyReading(value=7)))
        await tx.execute(sqlite.insert_many(Anchor, [Anchor(id=7), Anchor(id=9)]))
        await tx.execute(sqlite.insert(Payload(value=None, note=None)))
        scalar = sqlite.select(PolicyReading.value)
        named = (
            sqlite.select(Anchor)
            .left_join(PolicyReading, on=PolicyReading.value.eq_col(Anchor.id))
            .project(OnePolicy, value=PolicyReading.value)
            .order_by(Anchor.id.asc())
        )
        rejected = sqlite.select(PolicyReading).project(
            RejectPolicy, value=PolicyReading.value
        )

        async def read(query: Any, *, validate: bool) -> list[Any]:
            if mode == "buffered":
                return list(await tx.fetch_all(query, validate=validate))
            async with tx.fetch_chunks(query, size=1, validate=validate) as chunks:
                return [row async for chunk in chunks for row in chunk]

        for validate in (False, True, False):
            assert_eq(await read(scalar, validate=validate), [107 if validate else 207])
            rows = await read(named, validate=validate)
            assert_eq([row.value for row in rows], [1107 if validate else 1207, None])
            with assert_raises(ModelValidationError):
                await read(rejected, validate=validate)
            assert_eq(
                await read(sqlite.select(Payload.value), validate=validate), [None]
            )
            models = await read(sqlite.select(PolicyReading), validate=validate)
            assert_is(type(models[0]), PolicyReading)
            assert_eq(models[0].value, 7)
            with assert_raises(FrozenModelError):
                models[0].value = 8
