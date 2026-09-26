"""Schema verification must see columns backed by SQLite expressions."""

from typing import ClassVar

from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite


@test([Param("VIRTUAL", name="virtual"), Param("STORED", name="stored")], mark="medium")
async def undeclared_generated_column_is_drift(storage: str) -> None:
    """Computed columns still count as database columns absent from the model."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        number: sqlite.Col[int] = sqlite.Integer()

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE entry (number INTEGER NOT NULL, "
                f"doubled INTEGER GENERATED ALWAYS AS (number * 2) {storage}) STRICT"
            }
        )

        with assert_raises(sqlite.SchemaVerificationError) as raised:
            await database.verify([Entry])

    assert_eq(
        raised.exception.result.issues,
        (
            sqlite.SchemaDriftIssue(
                table_name="entry",
                detail="column 'doubled' exists in the database but not in the model",
            ),
        ),
    )


@test([Param("VIRTUAL", name="virtual"), Param("STORED", name="stored")], mark="medium")
async def declared_generated_column_has_comparable_metadata(storage: str) -> None:
    """Visible metadata can match without certifying the generation expression."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        number: sqlite.Col[int] = sqlite.Integer()
        doubled: sqlite.Col[int] = sqlite.Integer()

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE entry (number INTEGER NOT NULL, "
                "doubled INTEGER GENERATED ALWAYS AS (number * 2) "
                f"{storage} NOT NULL) STRICT"
            }
        )

        report = await database.verify([Entry])

    assert_eq(report.issues, ())
    assert_eq(
        [
            fact.status
            for fact in report.facts
            if fact.kind == "columns.generated_expressions"
        ],
        ["unchecked"],
    )
