"""Extrema retain their distinct source-policy and empty-input contracts."""

from typing import Any

from snektest import Param, assert_eq, assert_is, assert_raises, test

from snekql import sqlite
from snekql.errors import ModelValidationError
from tests.helpers import initialized_database
from tests.query.test_aggregate_validation import Reading
from tests.query.test_column_protocol_dispatch import (
    PolicyOnlySqlReading,
    PolicySqlReading,
    SqlReading,
)


@test(
    [Param(kind, name=kind) for kind in ("dialect", "policy", "policy_only")],
    [Param(mode, name=mode) for mode in ("buffered", "streamed")],
    mark="medium",
)
async def extrema_keep_policy_without_adopting_projection_hooks(
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
        query = sqlite.select(model.value.min(), model.value.max())
        for validate in (False, True, False):
            for empty in (False, True):
                selected = query.where(model.key.gt(99)) if empty else query
                if mode == "buffered":
                    rows = await tx.fetch_all(selected, validate=validate)
                else:
                    async with tx.fetch_chunks(
                        selected, size=1, validate=validate
                    ) as chunks:
                        rows = [row async for chunk in chunks for row in chunk]
                expected = (
                    (None, None)
                    if empty
                    else (7, 8)
                    if kind == "dialect"
                    else (107, 108)
                    if validate
                    else (207, 208)
                )
                assert_eq(rows, [expected])


@test([Param(mode, name=mode) for mode in ("buffered", "streamed")], mark="medium")
async def reused_extrema_keep_validation_and_other_aggregate_contracts(
    mode: str,
) -> None:
    async with (
        await initialized_database(database=":memory:", models=[Reading]) as db,
        db.transaction() as tx,
    ):
        await tx.execute(sqlite.raw("INSERT INTO reading (score) VALUES (-5), (7)"))
        query = sqlite.select(
            Reading.score.min(),
            Reading.score.max(),
            Reading.score.sum(),
            Reading.score.avg(),
            Reading.score.count(),
        )

        async def read(*, validate: bool, empty: bool) -> list[Any]:
            selected = query.where(Reading.score.gt(99)) if empty else query
            if mode == "buffered":
                return list(await tx.fetch_all(selected, validate=validate))
            async with tx.fetch_chunks(selected, size=1, validate=validate) as chunks:
                return [row async for chunk in chunks for row in chunk]

        for validate in (False, True, False):
            assert_eq(
                await read(validate=validate, empty=True), [(None, None, None, None, 0)]
            )
            if validate:
                with assert_raises(ModelValidationError):
                    await read(validate=True, empty=False)
            else:
                rows = await read(validate=False, empty=False)
                assert_eq(rows, [(-5, 7, 2, 1.0, 2)])
                assert_is(type(rows[0][2]), int)
                assert_is(type(rows[0][3]), float)
                assert_is(type(rows[0][4]), int)
