"""Logical operation gates must retry forward annotations after declaration."""

from typing import Annotated, ClassVar

from annotated_types import Ge
from pydantic import Json
from snektest import assert_eq, assert_raises, test

from snekql import sqlite
from tests.helpers import initialized_database


class LateReading[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[LateReading[sqlite.Row]]]
    value: sqlite.Col[LaterZoned] = sqlite.Text()


# Before the module alias exists, ordering is permissive for the unresolved type.
# Later calls must not keep that provisional answer.
EARLY_ORDERING = LateReading.value.asc()
LaterZoned = sqlite.ZonedDatetime


@test(mark="fast")
def late_zoned_annotation_eventually_rejects_ordering() -> None:
    with assert_raises(sqlite.QueryConstructionError):
        LateReading.value.asc()


class Measurement[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Measurement[sqlite.Row]]]
    quantity: sqlite.Col[Annotated[int, Ge(0)]] = sqlite.Integer()
    optional: sqlite.Col[int | None] = sqlite.Integer(default=None)
    flag: sqlite.Col[bool] = sqlite.Integer()
    payload: sqlite.Col[Json[int]] = sqlite.Text()


@test(mark="fast")
def warmed_columns_keep_independent_domains_and_constraints() -> None:
    Measurement.quantity.gte(0)
    Measurement.optional.asc()
    Measurement.flag.asc()
    Measurement.payload.asc()
    assert_eq(sqlite.select(Measurement.optional.sum()).compile().params, ())
    with assert_raises(sqlite.QueryConstructionError):
        Measurement.flag.sum()
    with assert_raises(sqlite.QueryConstructionError):
        Measurement.payload.add(1)
    with assert_raises(sqlite.ModelValidationError):
        sqlite.update(Measurement).set(Measurement.quantity.to(-1)).all().compile()
    assert_eq(
        sqlite.update(Measurement)
        .set(Measurement.quantity.to(True))
        .all()
        .compile()
        .params,
        (1,),
    )


@test(mark="medium")
async def aliases_retain_warmed_logical_types_and_nullable_aggregate_results() -> None:
    Measurement.quantity.asc()
    Measurement.optional.asc()

    class Role:
        pass

    alias = sqlite.alias(Measurement, Role, name="reading")
    shifted = sqlite.select(alias.column(Measurement.quantity).add(1))
    totals = sqlite.select(Measurement.quantity.sum(), Measurement.optional.sum())
    async with (
        await initialized_database(
            database=":memory:", models=[Measurement]
        ) as database,
        database.transaction() as tx,
    ):
        await tx.execute(sqlite.insert(Measurement(quantity=2, flag=True, payload=7)))
        assert_eq(await tx.fetch_all(shifted), [3])
        assert_eq(await tx.fetch_one(totals), (2, None))
        assert_eq(await tx.fetch_all(sqlite.select(Measurement.flag)), [True])
