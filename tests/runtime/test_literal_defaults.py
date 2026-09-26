"""Literal server defaults through declarations, writes, and verification."""

from dataclasses import FrozenInstanceError
from typing import Any, ClassVar

from pydantic import PositiveInt
from snektest import Param, assert_eq, assert_in, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import provide_mariadb_server


@test(mark="fast")
def literal_default_leaves_pending_value_omitted() -> None:
    """The marker supplies a database default, not a Python constructor value."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        attempts: sqlite.GenCol[int] = sqlite.Integer(default=sqlite.LiteralDefault(0))

    assert_eq(Entry().attempts, sqlite.PENDING_GENERATION)


@test(mark="fast")
def literal_default_scaffolds_integer() -> None:
    """A literal marker emits SQL DEFAULT without query parameters."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        attempts: sqlite.GenCol[int] = sqlite.Integer(default=sqlite.LiteralDefault(0))

    assert_in('"attempts" INTEGER NOT NULL DEFAULT 0', sqlite.scaffold([Entry]))


@test(mark="medium")
async def sqlite_supplies_omitted_text() -> None:
    """Escaped SQL-looking text is data when the database fills an omitted value."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        label: sqlite.GenCol[str] = sqlite.Text(
            default=sqlite.LiteralDefault("quote'\\nul\0; --é")
        )

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate({"001": sqlite.scaffold([Entry])})
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(Entry()))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(sqlite.select(Entry.label))

    assert_eq(rows, ["quote'\\nul\0; --é"])


@test(mark="slow")
async def mariadb_supplies_omitted_text() -> None:
    """Native string defaults do not depend on connection backslash escaping."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        label: mariadb.GenCol[str] = mariadb.Text(
            default=mariadb.LiteralDefault("quote'\\nul\0; --é")
        )

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([Entry])})
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Entry()))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(mariadb.select(Entry.label))

    assert_eq(rows, ["quote'\\nul\0; --é"])


@test(mark="medium")
async def sqlite_verifies_declared_literal() -> None:
    """Cosmetic parentheses do not hide a matching hand-created integer default."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        attempts: sqlite.GenCol[int] = sqlite.Integer(default=sqlite.LiteralDefault(7))

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE entry (attempts INTEGER NOT NULL DEFAULT ((+007))) STRICT"
            }
        )
        report = await database.verify([Entry])

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "column.server_default"],
        ["matched"],
    )


@test(
    [
        Param(value=case, name=case)
        for case in ("same", "changed", "missing", "expression", "null")
    ],
    mark="medium",
)
async def sqlite_classifies_default_catalog(case: str) -> None:
    """Known differences drift; an unknown expression is not certified."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        attempts: sqlite.GenCol[int] = sqlite.Integer(default=sqlite.LiteralDefault(7))

    clauses = {
        "same": "DEFAULT 7",
        "changed": "DEFAULT 8",
        "missing": "",
        "expression": "DEFAULT (abs(-7))",
        "null": "DEFAULT NULL",
    }
    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": f"CREATE TABLE entry (attempts INTEGER NOT NULL {clauses[case]}) STRICT"
            }
        )
        report = await database.verify([Entry], policy="warn")

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "column.server_default"],
        [
            {
                "same": "matched",
                "changed": "drift",
                "missing": "drift",
                "expression": "unchecked",
                "null": "drift",
            }[case]
        ],
    )


@test(mark="medium")
async def sqlite_verifies_nullable_null_default() -> None:
    """SQL NULL remains distinct from no declared default on SQLite."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        label: sqlite.GenCol[str | None] = sqlite.Text(
            nullable=True, default=sqlite.LiteralDefault(None)
        )

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate({"001": sqlite.scaffold([Entry])})
        report = await database.verify([Entry])

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "column.server_default"],
        ["matched"],
    )


@test(mark="slow")
async def mariadb_verifies_literal_text() -> None:
    """Scaffolded quoted text survives native catalog normalization."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        label: mariadb.GenCol[str] = mariadb.Text(
            default=mariadb.LiteralDefault("quote'\\nul\0; --é")
        )

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([Entry])})
        report = await database.verify([Entry])

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "column.server_default"],
        ["matched"],
    )


@test(mark="slow")
async def mariadb_discloses_null_default_ambiguity() -> None:
    """Effective SQL NULL can match without claiming an explicit DEFAULT clause."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        label: mariadb.GenCol[str | None] = mariadb.Text(
            nullable=True, default=mariadb.LiteralDefault(None)
        )

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE entry (label VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL) ENGINE=InnoDB"
            }
        )
        report = await database.verify([Entry])

    assert_eq(
        [
            (fact.kind, fact.status)
            for fact in report.facts
            if fact.kind.startswith("column.server_default")
        ],
        [
            ("column.server_default", "matched"),
            ("column.server_default_explicitness", "unchecked"),
        ],
    )


@test(mark="fast")
def literal_default_validates_logical_constraints() -> None:
    """A server-filled value must satisfy the same logical contract as a row."""
    with assert_raises(sqlite.ModelDeclarationError):

        class Entry[S = sqlite.Pending](sqlite.Model[S]):
            __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
            attempts: sqlite.GenCol[PositiveInt] = sqlite.Integer(
                default=sqlite.LiteralDefault(0)
            )


@test(
    [
        Param(value=case, name=case)
        for case in (
            "bool-as-int",
            "text-as-int",
            "too-large",
            "null",
            "not-generated",
            "auto-increment",
            "factory",
            "raw-sql",
        )
    ],
    mark="fast",
)
def invalid_default_is_rejected_before_io(case: str) -> None:
    """Bad declaration combinations never reach a driver."""
    marker: Any = sqlite.LiteralDefault(
        {
            "bool-as-int": True,
            "text-as-int": "7",
            "too-large": 2**80,
            "null": None,
            "raw-sql": "abs(-7)",
        }.get(case, 7)
    )
    options: Any = {"default": marker}
    if case == "auto-increment":
        options.update(primary_key=True, auto_increment=True)
    if case == "factory":
        options["default_factory"] = lambda: 0

    with assert_raises(sqlite.ModelDeclarationError):
        if case == "not-generated":

            class Entry[S = sqlite.Pending](sqlite.Model[S]):
                __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
                attempts: sqlite.Col[int] = sqlite.Integer(**options)
        else:

            class GeneratedEntry[S = sqlite.Pending](sqlite.Model[S]):
                __row_type__: ClassVar[sqlite.ReadType[GeneratedEntry[sqlite.Row]]]
                attempts: sqlite.GenCol[int] = sqlite.Integer(**options)


@test(mark="fast")
def mariadb_default_fits_declared_text_length() -> None:
    """A constant that cannot fit VARCHAR fails at declaration, not migration."""
    with assert_raises(mariadb.ModelDeclarationError):

        class Entry[S = mariadb.Pending](mariadb.Model[S]):
            __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
            label: mariadb.GenCol[str] = mariadb.Text(
                length=3, default=mariadb.LiteralDefault("long")
            )


@test(mark="slow")
async def mariadb_long_text_default_is_generated() -> None:
    """Ordinary long text accepts a server literal without the VARCHAR ceiling."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        label: mariadb.GenCol[str] = mariadb.LongText(
            default=mariadb.LiteralDefault("a" * 300)
        )

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([Entry])})
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Entry()))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(mariadb.select(Entry.label))

    assert_eq(rows, ["a" * 300])


@test(
    [Param(value=case, name=case) for case in ("omitted", "explicit", "null")],
    mark="medium",
)
async def sqlite_explicit_values_override_server_default(case: str) -> None:
    """Only PendingGeneration omits the column; explicit NULL is still a value."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        label: sqlite.GenCol[str | None] = sqlite.Text(
            nullable=True, default=sqlite.LiteralDefault("pending")
        )

    row = (
        Entry()
        if case == "omitted"
        else Entry(label="ready" if case == "explicit" else None)
    )
    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate({"001": sqlite.scaffold([Entry])})
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(row))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(sqlite.select(Entry.label))

    assert_eq(rows, [{"omitted": "pending", "explicit": "ready", "null": None}[case]])


@test(mark="medium")
async def sqlite_boolean_default_materializes() -> None:
    """A server Boolean constant decodes into the declared Python logical type."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        enabled: sqlite.GenCol[bool] = sqlite.Integer(
            default=sqlite.LiteralDefault(True)
        )

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate({"001": sqlite.scaffold([Entry])})
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(Entry()))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(sqlite.select(Entry))

    assert_eq([(type(row.enabled), row.enabled) for row in rows], [(bool, True)])


@test(
    [Param(value=case, name=case) for case in ("omitted", "explicit", "null")],
    mark="slow",
)
async def mariadb_explicit_values_override_server_default(case: str) -> None:
    """Only PendingGeneration omits the column; explicit NULL is still a value."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        label: mariadb.GenCol[str | None] = mariadb.Text(
            nullable=True, default=mariadb.LiteralDefault("pending")
        )

    row = (
        Entry()
        if case == "omitted"
        else Entry(label="ready" if case == "explicit" else None)
    )
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([Entry])})
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(row))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(mariadb.select(Entry.label))

    assert_eq(rows, [{"omitted": "pending", "explicit": "ready", "null": None}[case]])


@test(mark="slow")
async def mariadb_boolean_default_materializes() -> None:
    """A server Boolean constant decodes into the declared Python logical type."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        enabled: mariadb.GenCol[bool] = mariadb.Boolean(
            default=mariadb.LiteralDefault(True)
        )

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([Entry])})
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Entry()))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(mariadb.select(Entry))

    assert_eq([(type(row.enabled), row.enabled) for row in rows], [(bool, True)])


@test(mark="fast")
def table_foreign_key_can_have_literal_default() -> None:
    """A generated column may participate in a table-level foreign key."""

    class Parent[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Parent[sqlite.Row]]]
        key: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    class Child[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Child[sqlite.Row]]]
        parent_key: sqlite.GenCol[int] = sqlite.Integer(
            default=sqlite.LiteralDefault(7)
        )
        __foreign_keys__: ClassVar = [
            sqlite.ForeignKeyConstraint(parent_key, references=(Parent.key,))
        ]

    assert_in(
        '"parent_key" INTEGER NOT NULL DEFAULT 7', sqlite.scaffold([Parent, Child])
    )


@test(
    [
        Param(value=value, name=name)
        for name, value in (("float", 1.5), ("bytes", b"x"), ("mutable", [1]))
    ],
    mark="fast",
)
def marker_rejects_unsupported_literals(value: object) -> None:
    """A frozen literal marker cannot carry unsupported or mutable payloads."""
    with assert_raises(sqlite.ModelDeclarationError):
        sqlite.LiteralDefault(value)


@test(
    [
        Param(value=case, name=case)
        for case in ("same", "changed", "missing", "expression", "null")
    ],
    mark="slow",
)
async def mariadb_classifies_default_catalog(case: str) -> None:
    """Hand-created MariaDB defaults produce matched, drift, or unchecked facts."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        attempts: mariadb.GenCol[int | None] = mariadb.Integer(
            default=mariadb.LiteralDefault(7)
        )

    clauses = {
        "same": "DEFAULT 7",
        "changed": "DEFAULT 8",
        "missing": "",
        "expression": "DEFAULT (abs(-7))",
        "null": "DEFAULT NULL",
    }
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": f"CREATE TABLE entry (attempts BIGINT NULL {clauses[case]}) ENGINE=InnoDB"
            }
        )
        report = await database.verify([Entry], policy="warn")

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "column.server_default"],
        [
            {
                "same": "matched",
                "changed": "drift",
                "missing": "drift",
                "expression": "unchecked",
                "null": "drift",
            }[case]
        ],
    )


@test(mark="medium")
async def sqlite_null_default_materializes() -> None:
    """An omitted nullable value is supplied as SQL NULL."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        label: sqlite.GenCol[str | None] = sqlite.Text(
            default=sqlite.LiteralDefault(None)
        )

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate({"001": sqlite.scaffold([Entry])})
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(Entry()))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(sqlite.select(Entry.label))

    assert_eq(rows, [None])


@test(mark="fast")
def plain_default_does_not_emit_sql_default() -> None:
    """Existing Python defaults remain constructor values, not server defaults."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        attempts: sqlite.Col[int] = sqlite.Integer(default=7)

    assert_eq("DEFAULT" in sqlite.scaffold([Entry]), False)


@test(
    [
        Param(value=(value, sql, status), name=name)
        for name, value, sql, status in (
            ("null", None, "NULL", "matched"),
            ("quoted-null", "NULL", "'NULL'", "matched"),
            ("null-is-not-text", None, "'NULL'", "drift"),
            ("text-is-not-null", "NULL", "NULL", "drift"),
            ("empty", "", "''", "matched"),
            ("timestamp-name", "CurrentTimestamp", "'CurrentTimestamp'", "matched"),
            ("backslash", "a\\b", "'a\\b'", "matched"),
        )
    ],
    mark="medium",
)
async def sqlite_distinguishes_null_from_text(
    case: tuple[str | None, str, str],
) -> None:
    """A quoted constant is never mistaken for a keyword or missing default."""
    value, sql, status = case

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        label: sqlite.GenCol[str | None] = sqlite.Text(
            default=sqlite.LiteralDefault(value)
        )

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {"001": f"CREATE TABLE entry (label TEXT DEFAULT {sql}) STRICT"}
        )
        report = await database.verify([Entry], policy="warn")

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "column.server_default"],
        [status],
    )


@test(mark="fast")
def marker_is_immutable() -> None:
    """A declaration marker cannot silently change after model binding."""
    marker = sqlite.LiteralDefault(7)

    with assert_raises(FrozenInstanceError):
        marker.value = 8  # ty: ignore[invalid-assignment]


@test(mark="medium")
async def strict_policy_rejects_changed_literal() -> None:
    """Recognized literal drift fails strict verification."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        attempts: sqlite.GenCol[int] = sqlite.Integer(default=sqlite.LiteralDefault(7))

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {"001": "CREATE TABLE entry (attempts INTEGER NOT NULL DEFAULT 8) STRICT"}
        )
        with assert_raises(sqlite.SchemaVerificationError):
            await database.verify([Entry])


@test(mark="slow")
async def mariadb_nonnullable_absence_is_not_null_default() -> None:
    """A missing NOT NULL default does not supply an effective NULL value."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        label: mariadb.GenCol[str | None] = mariadb.Text(
            default=mariadb.LiteralDefault(None)
        )

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE entry (label VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL) ENGINE=InnoDB"
            }
        )
        report = await database.verify([Entry], policy="warn")

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "column.server_default"],
        ["drift"],
    )
