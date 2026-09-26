"""MariaDB VARCHAR capacity through declarations, scaffolding, and live verification."""

from typing import Any, ClassVar

from snektest import Param, assert_eq, assert_in, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import provide_mariadb_server


@test(mark="fast")
def scaffold_uses_declared_character_capacity() -> None:
    """An explicit length changes physical DDL without changing the string value family."""

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        label: mariadb.Col[str] = mariadb.Text(length=512)

    assert_in(
        "VARCHAR(512) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin",
        mariadb.scaffold([Entry]),
    )


@test(mark="fast")
def foreign_key_inherits_target_capacity() -> None:
    """Derived storage must retain length rather than silently reverting to VARCHAR(255)."""

    class Parent[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Parent[mariadb.Row]]]
        code: mariadb.Col[str] = mariadb.Text(length=80, primary_key=True)

    class Child[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Child[mariadb.Row]]]
        parent: mariadb.FKCol[Parent, str] = mariadb.ForeignKey(Parent.code)

    assert_in("`parent` VARCHAR(80)", mariadb.scaffold([Parent, Child]))


@test(
    [
        Param(value=1, name="minimum"),
        Param(value=255, name="default-size"),
        Param(value=16383, name="maximum"),
    ],
    mark="fast",
)
def valid_lengths_scaffold(length: int) -> None:
    """Declaration bounds describe character capacity, not guaranteed row/index fit."""

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        label: mariadb.Col[str] = mariadb.Text(length=length)

    assert_in(f"VARCHAR({length})", mariadb.scaffold([Entry]))


@test(
    [
        Param(value=0, name="zero"),
        Param(value=-1, name="negative"),
        Param(value=16384, name="too-large"),
        Param(value=True, name="boolean"),
    ],
    mark="fast",
)
def invalid_lengths_fail_at_declaration(length: int) -> None:
    """Invalid integer capacities fail before any database interaction."""
    with assert_raises(mariadb.ModelDeclarationError):
        mariadb.Text(length=length)


@test(
    [
        Param[object](value=None, name="none"),
        Param[object](value="80", name="string"),
        Param[object](value=80.0, name="float"),
    ],
    mark="fast",
)
def length_is_not_coerced(length: object) -> None:
    """The physical declaration accepts exact integers only."""
    with assert_raises(mariadb.ModelDeclarationError):
        mariadb.Text(length=length)  # ty: ignore[invalid-argument-type]


@test(mark="fast")
def omitted_length_preserves_existing_ddl() -> None:
    """Unconfigured Text remains VARCHAR(255) with the existing collation."""

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        label: mariadb.Col[str] = mariadb.Text()

    assert_in(
        "VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin",
        mariadb.scaffold([Entry]),
    )


@test(mark="fast")
def sqlite_does_not_accept_a_varchar_length() -> None:
    """SQLite TEXT does not gain a misleading VARCHAR capacity option."""
    with assert_raises(TypeError):
        sqlite.Text(length=80)  # ty: ignore[no-matching-overload]


@test(
    [Param(value=80, name="matching"), Param(value=255, name="mismatched")], mark="slow"
)
async def verify_hand_created_varchar(length: int) -> None:
    """Live verification compares the declared capacity against actual catalog length."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        __tablename__ = "length_entry"
        label: mariadb.Col[str] = mariadb.Text(length=80)

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": f"CREATE TABLE length_entry (label VARCHAR({length}) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL) ENGINE=InnoDB"
            }
        )
        if length == 80:
            assert_eq((await database.verify([Entry])).issues, ())
        else:
            with assert_raises(mariadb.SchemaVerificationError):
                await database.verify([Entry])


@test(mark="slow")
async def capacity_counts_characters_without_truncation() -> None:
    """Multibyte strings fit by character count; over-capacity writes fail on the server."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        __tablename__ = "length_entry"
        label: mariadb.Col[str] = mariadb.Text(length=2)

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE length_entry (label VARCHAR(2) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL) ENGINE=InnoDB"
            }
        )
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Entry(label="🐍é")))
        async with database.transaction() as transaction:
            value = await transaction.fetch_one(mariadb.select(Entry.label))
        assert_eq(value, "🐍é")
        with assert_raises(mariadb.ExecutionError):
            async with database.transaction() as transaction:
                await transaction.execute(mariadb.insert(Entry(label="abc")))


@test(mark="slow")
async def foreign_key_capacity_verifies_against_existing_tables() -> None:
    """A derived foreign key matches the target's native capacity in the live catalog."""
    server = await load_fixture(provide_mariadb_server())

    class Parent[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Parent[mariadb.Row]]]
        __tablename__ = "length_parent"
        code: mariadb.Col[str] = mariadb.Text(length=80, primary_key=True)

    class Child[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Child[mariadb.Row]]]
        __tablename__ = "length_child"
        code: mariadb.FKCol[Parent, str] = mariadb.ForeignKey(Parent.code)

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001_parent": "CREATE TABLE length_parent (code VARCHAR(80) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL PRIMARY KEY) ENGINE=InnoDB",
                "002_child": "CREATE TABLE length_child (code VARCHAR(80) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL, FOREIGN KEY (code) REFERENCES length_parent(code)) ENGINE=InnoDB",
            }
        )

        assert_eq((await database.verify([Parent, Child])).issues, ())


@test(mark="fast")
def length_preserves_defaults_and_nullability() -> None:
    """Capacity metadata does not turn Python defaults into SQL defaults or truncate values."""

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        label: mariadb.Col[str] = mariadb.Text(length=2, default="longer")
        optional: mariadb.Col[str | None] = mariadb.Text(length=80, default=None)
        factory: mariadb.Col[str] = mariadb.Text(
            length=30, default_factory=lambda: "value"
        )

    entry = Entry()
    assert_eq((entry.label, entry.optional, entry.factory), ("longer", None, "value"))
    assert_in("`optional` VARCHAR(80)", mariadb.scaffold([Entry]))


@test(mark="slow")
async def composite_keys_and_indexes_keep_declared_lengths() -> None:
    """Configurable strings preserve existing compound key and index declarations."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        __tablename__ = "length_entry"
        tenant: mariadb.Col[str] = mariadb.Text(length=16, primary_key=True)
        code: mariadb.Col[str] = mariadb.Text(length=40, primary_key=True)
        label: mariadb.Col[str] = mariadb.Text(length=80)
        __indexes__: ClassVar[list[mariadb.Index[Any]]] = [
            mariadb.Index(tenant, label, name="ix_length_lookup")
        ]

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE length_entry (tenant VARCHAR(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL, code VARCHAR(40) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL, label VARCHAR(80) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL, PRIMARY KEY (tenant, code), INDEX ix_length_lookup (tenant, label)) ENGINE=InnoDB",
            }
        )

        assert_eq((await database.verify([Entry])).issues, ())


@test(mark="slow")
async def larger_capacity_round_trips_beyond_legacy_codec_limit() -> None:
    """The previous 255-character codec ceiling cannot override an explicit larger VARCHAR."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        __tablename__ = "length_entry"
        label: mariadb.Col[str] = mariadb.Text(length=512)

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE length_entry (label VARCHAR(512) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL) ENGINE=InnoDB"
            }
        )
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Entry(label="x" * 300)))
        async with database.transaction() as transaction:
            value = await transaction.fetch_one(mariadb.select(Entry.label))
        assert_eq(value, "x" * 300)
