"""Catalog SQL NULL defaults do not imply schema drift."""

from __future__ import annotations

from snektest import Param, assert_eq, assert_in, assert_raises, load_fixture, test

from snekql import mariadb
from snekql.errors import SchemaVerificationError
from snekql.storage import SchemaPolicy
from tests.helpers import migrate_models, provide_mariadb_server


@test(
    [
        Param[SchemaPolicy](value="strict", name="strict"),
        Param[SchemaPolicy](value="warn", name="warn"),
    ],
    mark="slow",
)
async def nullable_scaffold_verifies(policy: SchemaPolicy) -> None:
    """Ordinary optional Integer and Text scaffolds satisfy strict verification."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S, "Entry[mariadb.Fetched]"]):
        amount: Entry.Col[int | None] = mariadb.Integer(default=None)
        text: Entry.Col[str | None] = mariadb.Text(default=None)

    async with await mariadb.Database.initialize(server.config()) as database:
        await migrate_models(database, [Entry])
        result = await database.verify([Entry], policy=policy)
    assert_eq(result.issues, ())


@test(
    [
        Param(value=literal, name=name)
        for name, literal in (
            ("sql_null", "NULL"),
            ("text_null", "'NULL'"),
            ("text_literal", "'other'"),
            ("expression", "(concat('N', 'ULL'))"),
        )
    ],
    mark="slow",
)
async def text_defaults_remain_distinct(literal: str) -> None:
    """Only unquoted SQL NULL is equivalent to the nullable scaffold default."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S, "Entry[mariadb.Fetched]"]):
        value: Entry.Col[str | None] = mariadb.Text(default=None)

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "create": (
                    "CREATE TABLE entry (value VARCHAR(255) CHARACTER SET utf8mb4 "
                    f"COLLATE utf8mb4_bin DEFAULT {literal}) ENGINE=InnoDB"
                )
            }
        )
        before = await server.run_sql("SHOW CREATE TABLE entry")
        catalog = await server.run_sql(
            "SELECT COLUMN_DEFAULT FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='entry'"
        )
        assert_in("NULL" if literal == "NULL" else "'", catalog.stdout)
        if literal == "NULL":
            assert_eq((await database.verify([Entry])).issues, ())
        else:
            with assert_raises(SchemaVerificationError):
                await database.verify([Entry])
        result = await database.verify([Entry], policy="warn")
        after = await server.run_sql("SHOW CREATE TABLE entry")
    assert_eq(len(result.issues), 0 if literal == "NULL" else 1)
    if result.issues:
        assert_in("server default expected None", result.issues[0].detail)
    assert_eq(after.stdout, before.stdout)


@test(mark="slow")
async def integer_literal_default_is_drift() -> None:
    """A non-NULL integer default must not be normalized away."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S, "Entry[mariadb.Fetched]"]):
        value: Entry.Col[int | None] = mariadb.Integer(default=None)

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {"create": "CREATE TABLE entry (value BIGINT DEFAULT 7)"}
        )
        with assert_raises(SchemaVerificationError):
            await database.verify([Entry])
        result = await database.verify([Entry], policy="warn")
    assert_eq(
        [issue.detail for issue in result.issues],
        ["column 'value' differs: server default expected None, found '7'"],
    )
