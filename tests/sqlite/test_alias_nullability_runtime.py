"""Named optional aliases agree across model, scaffold and live database behavior."""

from __future__ import annotations

from typing import Annotated

from pydantic import PlainSerializer
from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite
from snekql.errors import SchemaVerificationError
from tests.helpers import migrate_models

type OptionalInteger = int | None
type Maybe[T] = T | None


def double(value: int | None) -> int | None:
    """Make serializer retention visible in the stored wire value."""
    return value * 2 if value is not None else None


type SerializedOptional = Annotated[int | None, PlainSerializer(double)]


@test(
    [Param(value=None, name="default_none"), Param(value=7, name="integer")],
    mark="medium",
)
async def optional_alias_round_trip(value: int | None) -> None:
    """Scaffolded nullable columns accept both default None and ordinary values."""

    class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
        """Both alias forms declare nullable columns."""

        value: Entry.Col[OptionalInteger] = sqlite.Integer(default=None)
        generic: Entry.Col[Maybe[int]] = sqlite.Integer(default=None)

    async with await sqlite.Database.initialize(database=":memory:") as database:
        await migrate_models(database, [Entry])
        await database.verify([Entry])
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.insert(
                    Entry() if value is None else Entry(value=value, generic=value)
                )
            )
        async with database.transaction() as transaction:
            row = await transaction.fetch_one(
                sqlite.select(Entry.value, Entry.generic).all()
            )

    assert_eq(row, (value, value))


@test(mark="medium")
async def alias_serializer_is_preserved() -> None:
    """Nullability inspection must not replace Pydantic's original logical alias."""

    class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
        """A serializer on the alias controls the wire value."""

        value: Entry.Col[SerializedOptional] = sqlite.Integer(default=None)

    async with await sqlite.Database.initialize(database=":memory:") as database:
        await migrate_models(database, [Entry])
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(Entry(value=3)))
        async with database.transaction() as transaction:
            wire = await transaction.fetch_one(
                sqlite.select(Entry.value).all(), validate=False
            )

    assert_eq(wire, 6)


@test(mark="medium")
async def legacy_not_null_schema_is_not_rewritten() -> None:
    """Corrected inference reports old NOT NULL DDL as drift without altering it."""

    class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
        """An optional alias is authoritative even over an older schema."""

        value: Entry.Col[OptionalInteger] = sqlite.Integer(default=None)

    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate(
            {"legacy": "CREATE TABLE entry (value INTEGER NOT NULL) STRICT"}
        )
        with assert_raises(SchemaVerificationError):
            await database.verify([Entry])
        result = await database.verify([Entry], policy="warn")

    assert_eq(
        [issue.detail for issue in result.issues],
        ["column 'value' differs: nullable expected True, found False"],
    )
