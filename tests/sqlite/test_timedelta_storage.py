"""Bare timedelta storage behavior over SQLite Integer and Text columns."""

from __future__ import annotations

import warnings
from datetime import timedelta
from typing import cast

from snektest import assert_eq, assert_raises, test

from snekql._model_materialization import decode_model_row, encode_model_row
from snekql.sqlite import (
    ExecutionError,
    Fetched,
    Integer,
    LexicalDurationWarning,
    Model,
    Pending,
    Text,
    insert,
    select,
)
from tests.helpers import initialized_database


class IntegerDurationRow[S = Pending](Model[S, "IntegerDurationRow[Fetched]"]):
    """Table declaring a timedelta over an Integer storage class."""

    id: IntegerDurationRow.Col[int] = Integer(primary_key=True)
    elapsed: IntegerDurationRow.Col[timedelta] = Integer(nullable=False)


with warnings.catch_warnings():
    warnings.simplefilter("ignore", LexicalDurationWarning)

    class TextDurationRow[S = Pending](Model[S, "TextDurationRow[Fetched]"]):
        """Table declaring a timedelta over a Text storage class."""

        id: TextDurationRow.Col[int] = Integer(primary_key=True)
        elapsed: TextDurationRow.Col[timedelta] = Text(nullable=False)


@test()
def timedelta_encodes_as_iso_duration_text_even_over_integer() -> None:
    """The wire form for a bare timedelta is ISO-8601 duration text.

    The Integer storage class does not change the encoding: the integer range
    guard only inspects int wire values, so the text passes through untouched.
    """

    _, encoded = encode_model_row(
        IntegerDurationRow(id=1, elapsed=timedelta(seconds=9)),
        backend="sqlite",
    )

    assert_eq(encoded, {"id": 1, "elapsed": "PT9S"})


@test()
def negative_timedelta_encodes_as_sign_prefixed_duration_text() -> None:
    """A negative timedelta serializes with a leading sign on the text form."""

    _, encoded = encode_model_row(
        TextDurationRow(id=1, elapsed=timedelta(seconds=-5)),
        backend="sqlite",
    )

    assert_eq(encoded, {"id": 1, "elapsed": "-PT5S"})


@test()
def duration_text_decodes_back_to_timedelta() -> None:
    """Lax fetch decoding recovers the timedelta from duration text."""

    fetched = cast(
        "TextDurationRow[Fetched]",
        decode_model_row(
            TextDurationRow,
            {"id": 1, "elapsed": "PT9S"},
            backend="sqlite",
        ),
    )

    assert_eq(fetched.elapsed, timedelta(seconds=9))


@test()
def integer_database_value_decodes_as_whole_seconds() -> None:
    """Lax fetch decoding reads a numeric database value as whole seconds.

    Any future integer wire form must account for this: a stored millisecond
    count would silently decode as a thousandfold longer duration.
    """

    fetched = cast(
        "IntegerDurationRow[Fetched]",
        decode_model_row(
            IntegerDurationRow,
            {"id": 1, "elapsed": 9000},
            backend="sqlite",
        ),
    )

    assert_eq(fetched.elapsed, timedelta(seconds=9000))


@test(mark="medium")
async def strict_integer_column_rejects_duration_text_at_insert() -> None:
    """A snekql-created STRICT table refuses duration text bound to INTEGER.

    Type affinity would quietly store the text on a legacy non-STRICT table,
    but the scaffolded schema is STRICT, so the mismatch fails loudly at
    write time instead of lying about the declared storage.
    """

    database = await initialized_database(
        database=":memory:", models=[IntegerDurationRow]
    )
    try:
        with assert_raises(ExecutionError):
            async with database.transaction() as tx:
                await tx.execute(
                    insert(IntegerDurationRow(id=1, elapsed=timedelta(seconds=9)))
                )
    finally:
        await database.close()


@test(mark="medium")
async def text_column_round_trips_timedelta_values() -> None:
    """Duration text stored over Text decodes back to equal timedeltas."""

    database = await initialized_database(database=":memory:", models=[TextDurationRow])
    try:
        async with database.transaction() as tx:
            await tx.execute(
                insert(TextDurationRow(id=1, elapsed=timedelta(seconds=9)))
            )
            await tx.execute(
                insert(TextDurationRow(id=2, elapsed=timedelta(seconds=-5)))
            )
            fetched = await tx.fetch_all(
                select(TextDurationRow.elapsed).all().order_by(TextDurationRow.id.asc())
            )
    finally:
        await database.close()

    assert_eq(fetched, [timedelta(seconds=9), timedelta(seconds=-5)])


@test(mark="medium")
async def text_column_orders_durations_lexically_not_by_magnitude() -> None:
    """ORDER BY over duration text follows lexical, not logical, order.

    `'PT10S'` sorts before `'PT1H'`, which sorts before `'PT9M'` and `'PT9S'`,
    so ascending database order disagrees with the timedelta magnitudes.
    """

    database = await initialized_database(database=":memory:", models=[TextDurationRow])
    try:
        async with database.transaction() as tx:
            await tx.execute(
                insert(TextDurationRow(id=1, elapsed=timedelta(seconds=9)))
            )
            await tx.execute(
                insert(TextDurationRow(id=2, elapsed=timedelta(seconds=10)))
            )
            await tx.execute(
                insert(TextDurationRow(id=3, elapsed=timedelta(minutes=9)))
            )
            await tx.execute(insert(TextDurationRow(id=4, elapsed=timedelta(hours=1))))
            ordered_ids = await tx.fetch_all(
                select(TextDurationRow.id).all().order_by(TextDurationRow.elapsed.asc())
            )
    finally:
        await database.close()

    magnitude_order = [1, 2, 3, 4]
    assert_eq(ordered_ids, [2, 4, 3, 1])
    assert ordered_ids != magnitude_order
