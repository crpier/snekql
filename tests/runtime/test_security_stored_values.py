"""Malformed legacy rows retain safe built-in decoding diagnostics."""

from traceback import format_exception
from typing import ClassVar, Literal

from snektest import Param, assert_not_in, assert_raises, load_fixture, test

from snekql import mariadb
from tests.runtime.test_raw_execution import provide_raw_case


@test(
    [
        Param[Literal["scalar", "model", "stream"]]("scalar", name="scalar"),
        Param[Literal["scalar", "model", "stream"]]("model", name="model"),
        Param[Literal["scalar", "model", "stream"]]("stream", name="stream"),
    ],
    [Param(True, name="validated"), Param(False, name="unvalidated")],
    mark="slow",
)
async def legacy_datetime_traceback_omits_stored_text(
    consumption: Literal["scalar", "model", "stream"],
    validate: bool,  # noqa: FBT001 - snektest supplies parameter cases positionally
) -> None:
    """A mismatched legacy text column must not expose its invalid timestamp."""
    case = await load_fixture(provide_raw_case("mariadb"))

    class LegacyEvent[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[LegacyEvent[mariadb.Row]]]
        happened_at: mariadb.Col[mariadb.UtcDatetime] = mariadb.DateTime()

    private_text = "legacy_timestamp_private_value"
    await case.database.migrate(
        {"001": "CREATE TABLE legacy_event (happened_at TEXT NOT NULL)"}
    )
    async with case.database.transaction() as setup:
        await setup.execute(
            mariadb.raw("INSERT INTO legacy_event VALUES (%s)", params=(private_text,))
        )

    with assert_raises(mariadb.ModelValidationError) as caught:
        async with case.database.transaction() as transaction:
            if consumption == "model":
                await transaction.fetch_all(
                    mariadb.select(LegacyEvent), validate=validate
                )
            elif consumption == "stream":
                async with transaction.fetch_chunks(
                    mariadb.select(LegacyEvent.happened_at), size=1, validate=validate
                ) as stream:
                    await anext(stream)
            else:
                await transaction.fetch_all(
                    mariadb.select(LegacyEvent.happened_at), validate=validate
                )

    assert_not_in(private_text, "".join(format_exception(caught.exception)))
