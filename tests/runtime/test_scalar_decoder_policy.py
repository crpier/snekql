"""Scalar reads keep source policy and unconditional no-match NULL results."""

from typing import Any

from pydantic import BaseModel, field_validator
from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite
from snekql.errors import ModelValidationError
from tests.helpers import initialized_database
from tests.query.test_column_protocol_dispatch import (
    PolicyOnlySqlReading,
    PolicySqlReading,
    SqlReading,
)
from tests.runtime.test_derived_decoder_policy import Input
from tests.runtime.test_joined_row_shape import Anchor


@test(
    [Param(kind, name=kind) for kind in ("dialect", "policy", "policy_only")],
    [Param(mode, name=mode) for mode in ("buffered", "streamed")],
    mark="medium",
)
async def scalar_source_hooks_keep_validation_and_missing_nulls(
    kind: str, mode: str
) -> None:
    model: Any = {
        "dialect": SqlReading,
        "policy": PolicySqlReading,
        "policy_only": PolicyOnlySqlReading,
    }[kind]
    async with (
        await initialized_database(database=":memory:", models=[model, Anchor]) as db,
        db.transaction() as tx,
    ):
        await tx.execute(sqlite.insert_many(Anchor, [Anchor(id=1), Anchor(id=2)]))
        await tx.execute(sqlite.insert(model(key=1, value=7)))
        scalar = sqlite.scalar(
            sqlite.select(model.value).where(model.key.eq_col(Anchor.id))
        )
        query = sqlite.select(Anchor.id, scalar).order_by(Anchor.id.asc())
        for validate in (False, True, False):
            if mode == "buffered":
                rows = await tx.fetch_all(query, validate=validate)
            else:
                async with tx.fetch_chunks(query, size=1, validate=validate) as chunks:
                    rows = [row async for chunk in chunks for row in chunk]
            expected = {
                "dialect": 327,
                "policy": 127 if validate else 227,
                "policy_only": 107 if validate else 207,
            }[kind]
            assert_eq(rows, [(1, expected), (2, None)])


@test([Param(mode, name=mode) for mode in ("buffered", "streamed")], mark="medium")
async def scalar_query_reuse_retains_column_validation(mode: str) -> None:
    async with (
        await initialized_database(database=":memory:", models=[Input, Anchor]) as db,
        db.transaction() as tx,
    ):
        await tx.execute(sqlite.insert_many(Anchor, [Anchor(id=-5), Anchor(id=2)]))
        await tx.execute(sqlite.raw('INSERT INTO "input" (value) VALUES (-5)'))
        scalar = sqlite.scalar(
            sqlite.select(Input.value).where(Input.value.eq_col(Anchor.id))
        )
        query = sqlite.select(Anchor.id, scalar).order_by(Anchor.id.asc())

        async def read(*, validate: bool) -> list[object]:
            if mode == "buffered":
                return list(await tx.fetch_all(query, validate=validate))
            async with tx.fetch_chunks(query, size=1, validate=validate) as chunks:
                return [row async for chunk in chunks for row in chunk]

        assert_eq(await read(validate=False), [(-5, -5), (2, None)])
        with assert_raises(ModelValidationError):
            await read(validate=True)
        assert_eq(await read(validate=False), [(-5, -5), (2, None)])


class ScalarRows(BaseModel):
    key: int
    value: int | None

    @field_validator("value")
    @classmethod
    def intermediate_contract_does_not_run(cls, _value: int | None) -> int | None:
        msg = "scalar wire decoding must not validate an intermediate result"
        raise ValueError(msg)


class ScalarRole:
    """Named relation containing a correlated scalar output."""


@test([Param(mode, name=mode) for mode in ("buffered", "streamed")], mark="medium")
async def scalar_through_named_scalar_output_keeps_original_policy(mode: str) -> None:
    async with (
        await initialized_database(
            database=":memory:", models=[Anchor, PolicySqlReading]
        ) as db,
        db.transaction() as tx,
    ):
        await tx.execute(sqlite.insert_many(Anchor, [Anchor(id=1), Anchor(id=2)]))
        await tx.execute(sqlite.insert(PolicySqlReading(key=1, value=7)))
        key = Anchor.id.label("key")
        value = sqlite.scalar(
            sqlite.select(PolicySqlReading.value).where(
                PolicySqlReading.key.eq_col(Anchor.id)
            )
        ).label("value")
        definition = (
            sqlite.select(Anchor)
            .project(ScalarRows, key=key, value=value)
            .cte(ScalarRole, name="scalar_rows")
        )
        rebound = sqlite.scalar(
            sqlite.select(definition.column(value)).where(
                definition.column(key).eq_col(Anchor.id)
            )
        )
        query = sqlite.select(Anchor.id, rebound).order_by(Anchor.id.asc())
        for validate in (False, True, False):
            if mode == "buffered":
                rows = await tx.fetch_all(query, validate=validate)
            else:
                async with tx.fetch_chunks(query, size=1, validate=validate) as chunks:
                    rows = [row async for chunk in chunks for row in chunk]
            assert_eq(rows, [(1, 127 if validate else 227), (2, None)])
