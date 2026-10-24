"""Derived extrema decode their wire source, not intermediate result models."""

from typing import Any, cast

from pydantic import BaseModel, field_validator
from snektest import Param, assert_eq, assert_is, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.errors import ModelValidationError
from tests.helpers import initialized_database, provide_mariadb_server
from tests.query.test_column_protocol_dispatch import (
    PolicyOnlySqlReading,
    PolicySqlReading,
    SqlReading,
)
from tests.runtime.test_derived_decoder_policy import AliasRole, InnerRole, OuterRole
from tests.runtime.test_fixed_aggregate_decoder import NativeStatistics, SqlStatistics


class Intermediate(BaseModel):
    value: int

    @field_validator("value")
    @classmethod
    def reject_intermediate(cls, _value: int) -> int:
        msg = "intermediate model validation must not run"
        raise ValueError(msg)


class Result(BaseModel):
    low: int | None
    high: int | None

    @field_validator("low")
    @classmethod
    def transform_final(cls, value: int | None) -> int | None:
        return None if value is None else value + 1000


@test(
    [Param(kind, name=kind) for kind in ("dialect", "policy", "policy_only")],
    [Param(mode, name=mode) for mode in ("buffered", "streamed")],
    mark="medium",
)
async def derived_extrema_retain_projection_hooks_and_execution_policy(
    kind: str, mode: str
) -> None:
    model: Any = {
        "dialect": SqlReading,
        "policy": PolicySqlReading,
        "policy_only": PolicyOnlySqlReading,
    }[kind]
    async with (
        await initialized_database(database=":memory:", models=[model]) as db,
        db.transaction() as tx,
    ):
        await tx.execute(
            sqlite.insert_many(model, [model(key=1, value=7), model(key=2, value=8)])
        )
        for empty in (False, True):
            base = sqlite.select(model)
            if empty:
                base = base.where(model.key.gt(99))
            token = model.value.label("value")
            inner = base.project(Intermediate, value=token).cte(
                InnerRole, name="inner_values"
            )
            output = inner.column(token).label("value")
            outer = (
                sqlite.select(inner)
                .project(Intermediate, value=output)
                .cte(OuterRole, name="outer_values")
            )
            source = sqlite.alias(outer, AliasRole, name="values_alias")
            value = source.column(output)
            query = sqlite.select(source).project(
                Result, low=value.min(), high=value.max()
            )
            for validate in (False, True, False):
                if mode == "buffered":
                    rows = await tx.fetch_all(query, validate=validate)
                else:
                    async with tx.fetch_chunks(
                        query, size=1, validate=validate
                    ) as chunks:
                        rows = [row async for chunk in chunks for row in chunk]
                low, high = {
                    "dialect": (1327, 328),
                    "policy": (1127, 128) if validate else (1227, 228),
                    "policy_only": (1107, 108) if validate else (1207, 208),
                }[kind]
                result = cast("Result", rows[0])
                assert_eq(len(rows), 1)
                assert_eq(
                    (result.low, result.high), (None, None) if empty else (low, high)
                )


class Numbers(BaseModel):
    low: int | float | None
    high: int | None
    total: int | None

    @field_validator("low")
    @classmethod
    def transform_low(cls, value: int | float | None) -> int | float | None:
        return None if value is None else value + 1000


class IntermediateNumbers(Numbers):
    @field_validator("total")
    @classmethod
    def reject_intermediate(cls, _value: int | None) -> int | None:
        msg = "intermediate model validation must not run"
        raise ValueError(msg)


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [Param(mode, name=mode) for mode in ("buffered", "streamed")],
    [Param(kind, name=kind) for kind in ("columns", "aggregates")],
    mark="medium",
)
async def derived_extrema_keep_source_validation_domains_and_nulls(
    backend: str, mode: str, kind: str
) -> None:
    api: Any = sqlite if backend == "sqlite" else mariadb
    model: Any = SqlStatistics if backend == "sqlite" else NativeStatistics
    if backend == "sqlite":
        database = await initialized_database(
            database=":memory:", models=[SqlStatistics]
        )
        table = "sql_statistics"
    else:
        server = await load_fixture(provide_mariadb_server())
        database = await initialized_database(
            server.config(), models=[NativeStatistics]
        )
        table = "native_statistics"
    async with database as db, db.transaction() as tx:
        await tx.execute(
            api.raw(
                f"INSERT INTO {table} (id, units, custom) VALUES (1,-5,0),(2,2,0),(3,NULL,NULL)"
            )
        )
        for subset in ("all", "null", "empty"):
            base = api.select(model)
            if subset == "null":
                base = base.where(model.id.eq(3))
            if subset == "empty":
                base = base.where(model.id.gt(99))
            fields = (
                (model.units, model.units, model.units)
                if kind == "columns"
                else (model.units.avg(), model.units.count(), model.units.sum())
            )
            labels = tuple(
                field.label(name)
                for field, name in zip(fields, ("low", "high", "total"), strict=True)
            )
            source = base.project(
                IntermediateNumbers,
                **dict(zip(("low", "high", "total"), labels, strict=True)),
            ).cte(InnerRole, name="numbers")
            low, high, total = (source.column(label) for label in labels)
            query = api.select(source).project(
                Numbers, low=low.min(), high=high.max(), total=total.min()
            )

            async def read(validate: bool) -> list[Any]:
                if mode == "buffered":
                    return list(await tx.fetch_all(query, validate=validate))
                async with tx.fetch_chunks(query, size=1, validate=validate) as chunks:
                    return [row async for chunk in chunks for row in chunk]

            for validate in (False, True, False):
                if kind == "columns" and subset == "all" and validate:
                    with assert_raises(ModelValidationError):
                        await read(True)
                    continue
                rows = await read(validate)
                expected = (
                    ((995, 2, -5) if kind == "columns" else (998.5, 2, -3))
                    if subset == "all"
                    else ((None, None, None) if kind == "columns" else (None, 0, None))
                )
                assert_eq(len(rows), 1)
                result = cast("Numbers", rows[0])
                assert_eq((result.low, result.high, result.total), expected)
                if result.low is not None:
                    assert_is(type(result.low), int if kind == "columns" else float)
