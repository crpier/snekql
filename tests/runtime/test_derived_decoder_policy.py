"""Derived reads retain source codecs without validating intermediate results."""

from typing import Annotated, Any, ClassVar, cast

from annotated_types import Ge
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


class InnerRole:
    """First SQL definition."""


class OuterRole:
    """Second SQL definition."""


class AliasRole:
    """A consuming reference to the second definition."""


class Intermediate(BaseModel):
    value: int

    @field_validator("value")
    @classmethod
    def not_an_application_result(cls, _value: int) -> int:
        msg = "intermediate result validators must not run"
        raise ValueError(msg)


class Final(BaseModel):
    value: int

    @field_validator("value")
    @classmethod
    def application_transform(cls, value: int) -> int:
        return value + 1000


@test(
    [Param(kind, name=kind) for kind in ("dialect", "policy", "policy_only")],
    [Param(mode, name=mode) for mode in ("buffered", "streamed")],
    mark="medium",
)
async def nested_aliased_reads_retain_each_source_policy(kind: str, mode: str) -> None:
    model: Any = {
        "dialect": SqlReading,
        "policy": PolicySqlReading,
        "policy_only": PolicyOnlySqlReading,
    }[kind]
    async with (
        await initialized_database(database=":memory:", models=[model]) as db,
        db.transaction() as tx,
    ):
        await tx.execute(sqlite.insert(model(key=1, value=7)))
        token = model.value.label("value")
        inner = (
            sqlite.select(model)
            .project(Intermediate, value=token)
            .cte(InnerRole, name="inner_values")
        )
        outer = (
            sqlite.select(inner)
            .project(Final, value=inner.column(token))
            .cte(OuterRole, name="outer_values")
        )
        query = sqlite.select(sqlite.alias(outer, AliasRole, name="readings"))
        for validate in (False, True, False):
            if mode == "buffered":
                rows = await tx.fetch_all(query, validate=validate)
            else:
                async with tx.fetch_chunks(query, size=1, validate=validate) as chunks:
                    rows = [row async for chunk in chunks for row in chunk]
            expected = {
                "dialect": 1327,
                "policy": 1127 if validate else 1227,
                "policy_only": 1107 if validate else 1207,
            }[kind]
            assert_eq([cast("Final", row).value for row in rows], [expected])


class Input[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Input[sqlite.Row]]]
    value: Input.Col[Annotated[int, Ge(0)]] = sqlite.Integer()


@test([Param(mode, name=mode) for mode in ("buffered", "streamed")], mark="medium")
async def derived_query_reuse_does_not_retain_validation_policy(mode: str) -> None:
    async with (
        await initialized_database(database=":memory:", models=[Input]) as db,
        db.transaction() as tx,
    ):
        await tx.execute(sqlite.raw('INSERT INTO "input" (value) VALUES (-5)'))
        token = Input.value.label("value")
        definition = (
            sqlite.select(Input)
            .project(Intermediate, value=token)
            .cte(InnerRole, name="validated")
        )
        query = sqlite.select(definition).project(Final, value=definition.column(token))

        async def read(*, validate: bool) -> list[int]:
            if mode == "buffered":
                return [
                    cast("Final", row).value
                    for row in await tx.fetch_all(query, validate=validate)
                ]
            async with tx.fetch_chunks(query, size=1, validate=validate) as chunks:
                return [
                    cast("Final", row).value async for chunk in chunks for row in chunk
                ]

        assert_eq(await read(validate=False), [995])
        with assert_raises(ModelValidationError):
            await read(validate=True)
        assert_eq(await read(validate=False), [995])


class NullableResult(BaseModel):
    value: int | None


class PeerRole:
    """An independent physical relation."""


@test(
    [Param(context, name=context) for context in ("definition", "consumer")],
    [Param(mode, name=mode) for mode in ("buffered", "streamed")],
    mark="medium",
)
async def derived_null_extension_retains_each_query_scope(
    context: str, mode: str
) -> None:
    async with (
        await initialized_database(database=":memory:", models=[Input]) as db,
        db.transaction() as tx,
    ):
        await tx.execute(sqlite.insert_many(Input, [Input(value=1), Input(value=2)]))
        token = Input.value.label("value")
        peer = sqlite.alias(Input, PeerRole, name="peer")
        source = (
            sqlite.select(peer)
            .left_join(Input, on=peer.column(Input.value).eq(1) & Input.value.eq(1))
            .project(NullableResult, value=token)
            if context == "definition"
            else sqlite.select(Input)
            .where(Input.value.eq(1))
            .project(NullableResult, value=token)
        )
        inner = source.cte(InnerRole, name="inner_values")
        output = inner.column(token).label("value")
        outer = (
            sqlite.select(inner)
            .project(NullableResult, value=output)
            .cte(OuterRole, name="outer_values")
        )
        alias = sqlite.alias(outer, AliasRole, name="readings")
        query = (
            sqlite.select(alias)
            if context == "definition"
            else sqlite.select(Input)
            .left_join(alias, on=Input.value.eq(1))
            .project(NullableResult, value=alias.column(output))
        )
        if mode == "buffered":
            rows = await tx.fetch_all(query)
        else:
            async with tx.fetch_chunks(query, size=1) as chunks:
                rows = [row async for chunk in chunks for row in chunk]
        assert_eq(sorted((row.value for row in rows), key=lambda x: x or 0), [None, 1])
