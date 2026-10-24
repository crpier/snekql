"""Literal decoding follows returned SQL values, not the anchor's constant."""

from typing import Any

from pydantic import BaseModel, field_validator
from snektest import Param, assert_eq, assert_is, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.errors import ModelValidationError
from tests.query.test_literals import NativeSource, Source
from tests.runtime.test_literals import (
    provide_literal_source,
    provide_native_literal_source,
)


class Number(BaseModel):
    value: int | float


@test([Param(mode, name=mode) for mode in ("buffered", "streamed")], mark="medium")
async def literal_union_decodes_actual_values_and_rejects_native_type_drift(
    mode: str,
) -> None:
    database = await load_fixture(provide_literal_source())
    anchor = sqlite.select(Source).project(Number, value=sqlite.literal(0))
    invalid = anchor.union_all(
        sqlite.select(Source).project(Number, value=Source.id.add(2**63 - 1))
    )
    valid = anchor.union_all(
        sqlite.select(Source).project(Number, value=Source.id.add(2))
    )
    async with database.transaction() as tx:

        async def read(query: Any, *, validate: bool) -> list[Any]:
            if mode == "buffered":
                return list(await tx.fetch_all(query, validate=validate))
            async with tx.fetch_chunks(query, size=1, validate=validate) as chunks:
                return [row async for chunk in chunks for row in chunk]

        for validate in (False, True, False):
            with assert_raises(ModelValidationError):
                await read(invalid, validate=validate)
            rows = await read(valid, validate=validate)
            assert_eq([row.value for row in rows], [0, 3])
            assert_is(type(rows[1].value), int)


class Role:
    pass


class PeerRole:
    pass


class Intermediate(BaseModel):
    low: int
    high: int

    @field_validator("low")
    @classmethod
    def reject_intermediate(cls, _value: int) -> int:
        msg = "intermediate model must not be constructed"
        raise ValueError(msg)


class Pair(BaseModel):
    low: int | None
    high: int | None

    @field_validator("low")
    @classmethod
    def transform_final(cls, value: int | None) -> int | None:
        return None if value is None else value + 1


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [Param(mode, name=mode) for mode in ("buffered", "streamed")],
    mark="medium",
)
async def literal_ranges_keep_owner_free_and_derived_null_contexts(
    backend: str, mode: str
) -> None:
    api: Any = sqlite if backend == "sqlite" else mariadb
    model: Any = Source if backend == "sqlite" else NativeSource
    database = await load_fixture(
        provide_literal_source()
        if backend == "sqlite"
        else provide_native_literal_source()
    )
    low, high = api.literal(-(2**63)).label("low"), api.literal(2**63 - 1).label("high")
    peer = api.alias(model, PeerRole, name="peer")
    base = api.select(model).left_join(peer, on=peer.column(model.id).eq(99))
    direct = base.project(Pair, low=low, high=high)
    source = base.project(Intermediate, low=low, high=high).cte(Role, name="constants")
    present = api.select(source).project(
        Pair, low=source.column(low), high=source.column(high)
    )
    absent = (
        api.select(model)
        .left_join(source, on=source.column(low).eq(3))
        .project(Pair, low=source.column(low), high=source.column(high))
    )
    empty_scalar = api.select(model).project(
        Pair,
        low=api.scalar(api.select(source.column(low)).where(source.column(low).eq(3))),
        high=api.literal(2**63 - 1),
    )
    async with database.transaction() as tx:
        for validate in (False, True, False):
            for query, expected in (
                (direct, (-(2**63) + 1, 2**63 - 1)),
                (present, (-(2**63) + 1, 2**63 - 1)),
                (absent, (None, None)),
                (empty_scalar, (None, 2**63 - 1)),
            ):
                if mode == "buffered":
                    rows = await tx.fetch_all(query, validate=validate)
                else:
                    async with tx.fetch_chunks(
                        query, size=2, validate=validate
                    ) as chunks:
                        rows = [row async for chunk in chunks for row in chunk]
                assert_eq([(row.low, row.high) for row in rows], [expected])
                if rows[0].low is not None:
                    assert_is(type(rows[0].low), int)


class IntermediateStep(BaseModel):
    value: int

    @field_validator("value")
    @classmethod
    def reject_intermediate(cls, _value: int) -> int:
        msg = "recursive intermediate model must not be constructed"
        raise ValueError(msg)


class Step(BaseModel):
    value: int

    @field_validator("value")
    @classmethod
    def transform_final(cls, value: int) -> int:
        return value + 100


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [Param(mode, name=mode) for mode in ("buffered", "streamed")],
    mark="medium",
)
async def recursive_literal_anchor_decodes_each_step_before_final_validation(
    backend: str, mode: str
) -> None:
    api: Any = sqlite if backend == "sqlite" else mariadb
    model: Any = Source if backend == "sqlite" else NativeSource
    database = await load_fixture(
        provide_literal_source()
        if backend == "sqlite"
        else provide_native_literal_source()
    )
    token = api.literal(0).label("value")
    anchor = api.select(model).project(IntermediateStep, value=token)
    walk = api.recursive_cte(anchor, Role, name="walk").step(
        lambda previous: (
            api.select(previous)
            .where(previous.column(token).lt(2))
            .project(IntermediateStep, value=previous.column(token).add(1))
        )
    )
    query = (
        api.select(walk)
        .project(Step, value=walk.column(token))
        .order_by(walk.column(token).asc())
    )
    async with database.transaction() as tx:
        for validate in (False, True, False):
            if mode == "buffered":
                rows = await tx.fetch_all(query, validate=validate)
            else:
                async with tx.fetch_chunks(query, size=2, validate=validate) as chunks:
                    rows = [row async for chunk in chunks for row in chunk]
            assert_eq([row.value for row in rows], [100, 101, 102])
            assert_is(type(rows[-1].value), int)
