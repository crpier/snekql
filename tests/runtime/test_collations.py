"""Declared column collations control database comparison semantics."""

from typing import Any, ClassVar, Literal

from snektest import Param, assert_eq, assert_in, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import provide_mariadb_server


@test(mark="fast")
def sqlite_scaffold_declares_nocase() -> None:
    """An explicit text collation belongs to the physical column definition."""

    class Label[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Label[sqlite.Row]]]
        name: sqlite.Col[str] = sqlite.Text(collation="NOCASE")

    assert_in("TEXT COLLATE NOCASE", sqlite.scaffold([Label]))


@test(mark="fast")
def mariadb_scaffold_declares_unicode_collation() -> None:
    """VARCHAR and LONGTEXT retain their utf8mb4 character set with a chosen collation."""

    class Label[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Label[mariadb.Row]]]
        name: mariadb.Col[str] = mariadb.Text(length=80, collation="utf8mb4_unicode_ci")
        body: mariadb.Col[str] = mariadb.LongText(collation="utf8mb4_general_ci")

    ddl = mariadb.scaffold([Label])
    assert_in("VARCHAR(80) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci", ddl)
    assert_in("LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci", ddl)


@test(mark="fast")
def sqlite_foreign_key_inherits_collation() -> None:
    """A scalar foreign key declares the target's comparison policy."""

    class Parent[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Parent[sqlite.Row]]]
        code: sqlite.Col[str] = sqlite.Text(primary_key=True, collation="NOCASE")

    class Child[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Child[sqlite.Row]]]
        code: sqlite.FKCol[Parent, str] = sqlite.ForeignKey(Parent.code)

    assert_eq(sqlite.scaffold([Parent, Child]).count("COLLATE NOCASE"), 2)


@test(
    [
        Param(value=name, name=str(name))
        for name in (
            None,
            "",
            "nocase",
            "custom",
            "utf8mb4_bin",
            "NOCASE; DROP TABLE x",
            1,
            True,
            [],
        )
    ],
    mark="fast",
)
def sqlite_rejects_unsupported_collations(name: Any) -> None:
    """Invalid names fail at declaration, including untyped and SQL-fragment input."""
    with assert_raises(sqlite.ModelDeclarationError):
        sqlite.Text(collation=name)


@test(
    [
        Param(value=(kind, name), name=f"{kind}-{name!r}")
        for kind in ("varchar", "longtext")
        for name in (
            None,
            "",
            "UTF8MB4_BIN",
            "custom",
            "BINARY",
            "latin1_bin",
            "utf8mb4_bin; DROP TABLE x",
            1,
            True,
            [],
        )
    ],
    mark="fast",
)
def mariadb_rejects_unsupported_collations(case: tuple[str, Any]) -> None:
    """Both native text declarations reject names outside the reviewed utf8mb4 set."""
    kind, name = case
    with assert_raises(mariadb.ModelDeclarationError):
        if kind == "varchar":
            mariadb.Text(collation=name)
        else:
            mariadb.LongText(collation=name)


type SQLiteCollation = Literal["BINARY", "NOCASE", "RTRIM"]
type MariaDBCollation = Literal[
    "utf8mb4_bin", "utf8mb4_general_ci", "utf8mb4_unicode_ci"
]


_SQLITE_COLLATIONS: tuple[SQLiteCollation, ...] = ("BINARY", "NOCASE", "RTRIM")
_MARIADB_COLLATIONS: tuple[MariaDBCollation, ...] = (
    "utf8mb4_bin",
    "utf8mb4_general_ci",
    "utf8mb4_unicode_ci",
)


@test(
    [
        Param(value=(expected, actual), name=f"{expected}-{actual}")
        for expected in _SQLITE_COLLATIONS
        for actual in _SQLITE_COLLATIONS
    ],
    mark="fast",
)
async def sqlite_verifies_hand_created_collations(
    case: tuple[SQLiteCollation, SQLiteCollation],
) -> None:
    """Matching physical collations verify; other supported choices remain drift."""
    expected, actual = case

    class Label[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Label[sqlite.Row]]]
        __tablename__ = "collation_label"
        name: sqlite.Col[str] = sqlite.Text(collation=expected)

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": f"CREATE TABLE collation_label (name TEXT COLLATE {actual} NOT NULL) STRICT"
            }
        )
        if expected == actual:
            assert_eq((await database.verify([Label])).issues, ())
        else:
            with assert_raises(sqlite.SchemaVerificationError):
                await database.verify([Label])


@test(
    [
        Param(value=(kind, expected, actual), name=f"{kind}-{expected}-{actual}")
        for kind in ("varchar", "longtext")
        for expected in _MARIADB_COLLATIONS
        for actual in _MARIADB_COLLATIONS
    ],
    mark="slow",
)
async def mariadb_verifies_hand_created_collations(
    case: tuple[str, MariaDBCollation, MariaDBCollation],
) -> None:
    """Both string storage types compare their declared collation against catalog evidence."""
    server = await load_fixture(provide_mariadb_server())
    kind, expected, actual = case

    class Label[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Label[mariadb.Row]]]
        __tablename__ = "collation_label"
        name: mariadb.Col[str] = (
            mariadb.Text(collation=expected)
            if kind == "varchar"
            else mariadb.LongText(collation=expected)
        )

    sql_type = "VARCHAR(255)" if kind == "varchar" else "LONGTEXT"
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": f"CREATE TABLE collation_label (name {sql_type} CHARACTER SET utf8mb4 COLLATE {actual} NOT NULL) ENGINE=InnoDB"
            }
        )
        if expected == actual:
            assert_eq((await database.verify([Label])).issues, ())
        else:
            with assert_raises(mariadb.SchemaVerificationError):
                await database.verify([Label])


type SQLiteComparison = tuple[SQLiteCollation, str, str, bool]
type MariaDBComparison = tuple[MariaDBCollation, str, str, bool]


@test(
    [
        Param[SQLiteComparison](
            value=("BINARY", "Alpha", "alpha", False), name="binary-case-sensitive"
        ),
        Param[SQLiteComparison](
            value=("NOCASE", "Alpha", "alpha", True), name="nocase-ascii"
        ),
        Param[SQLiteComparison](
            value=("NOCASE", "Ä", "ä", False), name="nocase-not-unicode"
        ),
        Param[SQLiteComparison](
            value=("RTRIM", "alpha ", "alpha", True), name="rtrim-space"
        ),
        Param[SQLiteComparison](
            value=("RTRIM", "alpha\t", "alpha", False), name="rtrim-not-tab"
        ),
        Param[SQLiteComparison](
            value=("BINARY", "alpha ", "alpha", False), name="binary-preserves-space"
        ),
    ],
    mark="fast",
)
async def sqlite_equality_uses_column_collation(case: SQLiteComparison) -> None:
    """SQL equality uses the selected built-in rule without changing stored Python strings."""
    collation, stored, probe, matches = case

    class Label[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Label[sqlite.Row]]]
        name: sqlite.Col[str] = sqlite.Text(collation=collation)

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate({"001": sqlite.scaffold([Label])})
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(Label(name=stored)))
        async with database.transaction() as transaction:
            received = await transaction.fetch_all(
                sqlite.select(Label.name).where(Label.name.eq(probe))
            )
        assert_eq(received, [stored] if matches else [])


@test(
    [
        Param[MariaDBComparison](
            value=("utf8mb4_bin", "Alpha", "alpha", False), name="binary-case-sensitive"
        ),
        Param[MariaDBComparison](
            value=("utf8mb4_bin", "alpha ", "alpha", True), name="binary-pad-space"
        ),
        Param[MariaDBComparison](
            value=("utf8mb4_general_ci", "Alpha", "alpha", True),
            name="general-case-insensitive",
        ),
        Param[MariaDBComparison](
            value=("utf8mb4_unicode_ci", "café", "CAFE", True),
            name="unicode-case-accent-insensitive",
        ),
    ],
    mark="slow",
)
async def mariadb_equality_uses_column_collation(case: MariaDBComparison) -> None:
    """Native VARCHAR comparisons follow database collation, not Python equality."""
    server = await load_fixture(provide_mariadb_server())
    collation, stored, probe, matches = case

    class Label[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Label[mariadb.Row]]]
        name: mariadb.Col[str] = mariadb.Text(collation=collation)

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([Label])})
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Label(name=stored)))
        async with database.transaction() as transaction:
            received = await transaction.fetch_all(
                mariadb.select(Label.name).where(Label.name.eq(probe))
            )
        assert_eq(received, [stored] if matches else [])


@test(mark="slow")
async def long_text_equality_uses_unicode_collation() -> None:
    """LongText's chosen collation participates in ordinary equality predicates."""
    server = await load_fixture(provide_mariadb_server())

    class Label[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Label[mariadb.Row]]]
        name: mariadb.Col[str] = mariadb.LongText(collation="utf8mb4_unicode_ci")

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([Label])})
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Label(name="café")))
        async with database.transaction() as transaction:
            received = await transaction.fetch_all(
                mariadb.select(Label.name).where(Label.name.eq("CAFE"))
            )
        assert_eq(received, ["café"])


@test(mark="fast")
async def sqlite_unique_key_uses_nocase() -> None:
    """Unique keys reject distinct Python strings that the database considers equal."""

    class Label[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Label[sqlite.Row]]]
        name: sqlite.Col[str] = sqlite.Text(primary_key=True, collation="NOCASE")

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate({"001": sqlite.scaffold([Label])})
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(Label(name="Alpha")))
        with assert_raises(sqlite.ExecutionError):
            async with database.transaction() as transaction:
                await transaction.execute(sqlite.insert(Label(name="alpha")))


@test(mark="slow")
async def mariadb_unique_key_uses_unicode_collation() -> None:
    """Native keys apply case/accent equivalence independently of Python strings."""
    server = await load_fixture(provide_mariadb_server())

    class Label[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Label[mariadb.Row]]]
        name: mariadb.Col[str] = mariadb.Text(
            primary_key=True, collation="utf8mb4_unicode_ci"
        )

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([Label])})
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Label(name="café")))
        with assert_raises(mariadb.ExecutionError):
            async with database.transaction() as transaction:
                await transaction.execute(mariadb.insert(Label(name="CAFE")))


@test(mark="slow")
async def mariadb_foreign_key_inherits_collation() -> None:
    """Foreign-key DDL and verification retain the target's native collation."""
    server = await load_fixture(provide_mariadb_server())

    class Parent[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Parent[mariadb.Row]]]
        code: mariadb.Col[str] = mariadb.Text(
            primary_key=True, collation="utf8mb4_unicode_ci"
        )

    class Child[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Child[mariadb.Row]]]
        code: mariadb.FKCol[Parent, str] = mariadb.ForeignKey(Parent.code)

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([Parent, Child])})
        assert_eq((await database.verify([Parent, Child])).issues, ())
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Parent(code="café")))
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Child(code="CAFE")))
        async with database.transaction() as transaction:
            received = await transaction.fetch_all(
                mariadb.select(Child.code).where(Child.code.eq("café"))
            )
        assert_eq(received, ["CAFE"])


@test(mark="fast")
async def sqlite_foreign_key_matches_parent_collation() -> None:
    """A foreign key keeps parent NOCASE semantics through DDL and verification."""

    class Parent[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Parent[sqlite.Row]]]
        code: sqlite.Col[str] = sqlite.Text(primary_key=True, collation="NOCASE")

    class Child[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Child[sqlite.Row]]]
        code: sqlite.FKCol[Parent, str] = sqlite.ForeignKey(Parent.code)

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate({"001": sqlite.scaffold([Parent, Child])})
        assert_eq((await database.verify([Parent, Child])).issues, ())
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(Parent(code="Alpha")))
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(Child(code="alpha")))
        async with database.transaction() as transaction:
            received = await transaction.fetch_all(
                sqlite.select(Child.code).where(Child.code.eq("Alpha"))
            )
        assert_eq(received, ["alpha"])


@test(
    [
        Param(value="name TEXT COLLATE BINARY COLLATE NOCASE", name="last-clause-wins"),
        Param(value="name TEXT COLLATE 'nocase'", name="quoted-name"),
        Param(value="'name' TEXT COLLATE NOCASE", name="quoted-column"),
    ],
    mark="fast",
)
async def sqlite_verifies_effective_collation(clause: str) -> None:
    """SQLite's accepted spelling and repeated clauses must resolve to its effective collation."""

    class Label[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Label[sqlite.Row]]]
        __tablename__ = "collation_label"
        name: sqlite.Col[str] = sqlite.Text(collation="NOCASE")

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {"001": f"CREATE TABLE collation_label ({clause} NOT NULL) STRICT"}
        )
        assert_eq((await database.verify([Label])).issues, ())
