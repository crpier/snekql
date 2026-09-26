"""MariaDB prefix indexes through declarations, scaffold, and native behavior."""

from dataclasses import FrozenInstanceError
from typing import Any, ClassVar

from pydantic import Json
from snektest import Param, assert_eq, assert_in, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import provide_mariadb_server


@test(mark="fast")
def ordered_prefix_scaffold() -> None:
    """A mixed full-column and text-prefix index preserves member order."""

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        tenant_id: mariadb.Col[int] = mariadb.Integer()
        title: mariadb.Col[str] = mariadb.Text(length=1000)
        __indexes__: ClassVar = [
            mariadb.Index(tenant_id, title, prefix_lengths=(None, 128), name="ix_title")
        ]

    assert_in(
        "CREATE INDEX `ix_title` ON `entry` (`tenant_id`, `title`(128))",
        mariadb.scaffold([Entry]),
    )


@test(
    [
        Param(value=value, name=name)
        for name, value in (
            ("short", ()),
            ("long", (1, 2)),
            ("zero", (0,)),
            ("negative", (-1,)),
            ("bool", (True,)),
            ("float", (1.5,)),
            ("text", ("1",)),
            ("capacity", (11,)),
            ("list", [1]),
            ("scalar", 1),
        )
    ],
    mark="fast",
)
def invalid_prefix_declaration(prefixes: Any) -> None:
    """Prefix counts and lengths are validated before DDL can be emitted."""
    with assert_raises(mariadb.ModelDeclarationError):

        class Entry[S = mariadb.Pending](mariadb.Model[S]):
            __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
            title: mariadb.Col[str] = mariadb.Text(length=10)
            __indexes__: ClassVar = [mariadb.Index(title, prefix_lengths=prefixes)]


@test(mark="fast")
def long_text_prefix_scaffold() -> None:
    """LONGTEXT becomes indexable only through an explicit character prefix."""

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        title: mariadb.Col[str] = mariadb.LongText()
        __indexes__: ClassVar = [mariadb.Index(title, prefix_lengths=(128,))]

    assert_in("ON `entry` (`title`(128))", mariadb.scaffold([Entry]))


@test(mark="fast")
def sqlite_rejects_prefixes() -> None:
    """Even an all-full prefix option is not a SQLite declaration."""
    with assert_raises(sqlite.ModelDeclarationError):

        class Entry[S = sqlite.Pending](sqlite.Model[S]):
            __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
            title: sqlite.Col[str] = sqlite.Text()
            __indexes__: ClassVar = [sqlite.Index(title, prefix_lengths=(None,))]


@test(mark="fast")
def integer_rejects_prefix() -> None:
    """Character prefixes cannot be attached to numeric storage."""
    with assert_raises(mariadb.ModelDeclarationError):

        class Entry[S = mariadb.Pending](mariadb.Model[S]):
            __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
            number: mariadb.Col[int] = mariadb.Integer()
            __indexes__: ClassVar = [mariadb.Index(number, prefix_lengths=(1,))]


@test(mark="fast")
def encoded_text_rejects_prefix() -> None:
    """A JSON text codec is not ordinary string prefix indexing."""
    with assert_raises(mariadb.ModelDeclarationError):

        class Entry[S = mariadb.Pending](mariadb.Model[S]):
            __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
            title: mariadb.Col[Json[str]] = mariadb.Text()
            __indexes__: ClassVar = [mariadb.Index(title, prefix_lengths=(1,))]


@test(mark="slow")
async def hand_created_prefix_matches() -> None:
    """Catalog SUB_PART values match ordered full and prefix declarations."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        tenant_id: mariadb.Col[int] = mariadb.Integer()
        title: mariadb.Col[str] = mariadb.LongText()
        __indexes__: ClassVar = [
            mariadb.Index(tenant_id, title, prefix_lengths=(None, 128), name="ix_title")
        ]

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE entry (tenant_id BIGINT NOT NULL, title LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL, INDEX ix_title (tenant_id, title(128))) ENGINE=InnoDB"
            }
        )
        report = await database.verify([Entry])

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "index.prefix_lengths"],
        ["matched"],
    )


@test(mark="fast")
def prefix_unique_is_not_table_foreign_key_target() -> None:
    """Prefix uniqueness cannot authorize a complete-value foreign key."""

    class Parent[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Parent[mariadb.Row]]]
        title: mariadb.Col[str] = mariadb.Text()
        __indexes__: ClassVar = [mariadb.Index(title, unique=True, prefix_lengths=(3,))]

    with assert_raises(mariadb.ModelDeclarationError):

        class Child[S = mariadb.Pending](mariadb.Model[S]):
            __row_type__: ClassVar[mariadb.ReadType[Child[mariadb.Row]]]
            title: mariadb.Col[str] = mariadb.Text()
            __foreign_keys__: ClassVar = [
                mariadb.ForeignKeyConstraint(title, references=(Parent.title,))
            ]


@test(mark="fast")
def prefix_unique_is_not_scalar_foreign_key_target() -> None:
    """The scalar storage-deriving declaration also needs full-column uniqueness."""

    class Parent[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Parent[mariadb.Row]]]
        title: mariadb.Col[str] = mariadb.Text()
        __indexes__: ClassVar = [mariadb.Index(title, unique=True, prefix_lengths=(3,))]

    class Child[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Child[mariadb.Row]]]
        title: mariadb.FKCol[Parent, str] = mariadb.ForeignKey(Parent.title)

    with assert_raises(mariadb.SchemaError):
        mariadb.scaffold([Parent, Child])


@test(mark="slow")
async def unmanaged_prefix_is_not_hidden_as_fk_support() -> None:
    """An extra partial-value index remains drift beside a real supporting index."""
    server = await load_fixture(provide_mariadb_server())

    class Parent[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Parent[mariadb.Row]]]
        title: mariadb.Col[str] = mariadb.Text(primary_key=True)

    class Child[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Child[mariadb.Row]]]
        title: mariadb.FKCol[Parent, str] = mariadb.ForeignKey(Parent.title)

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": mariadb.scaffold([Parent, Child]),
                "002": "CREATE INDEX ix_prefix ON child (title(3))",
            }
        )
        report = await database.verify([Child], policy="warn")

    assert_eq(
        [
            (fact.object_name, fact.status)
            for fact in report.facts
            if fact.kind == "index.presence"
        ],
        [("ix_prefix", "drift")],
    )


@test(mark="fast")
def distinct_prefixes_can_coexist() -> None:
    """Named full and prefix indexes can share the same ordered columns."""

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        title: mariadb.Col[str] = mariadb.Text()
        __indexes__: ClassVar = [
            mariadb.Index(title, name="ix_full"),
            mariadb.Index(title, name="ix_short", prefix_lengths=(3,)),
            mariadb.Index(title, name="ix_long", prefix_lengths=(8,)),
        ]

    assert_eq(
        [
            sql.strip()
            for sql in mariadb.scaffold([Entry]).split(";")
            if "CREATE INDEX" in sql
        ],
        [
            "CREATE INDEX `ix_full` ON `entry` (`title`)",
            "CREATE INDEX `ix_short` ON `entry` (`title`(3))",
            "CREATE INDEX `ix_long` ON `entry` (`title`(8))",
        ],
    )


@test(
    [Param(value="varchar", name="varchar"), Param(value="longtext", name="longtext")],
    mark="slow",
)
async def unique_prefix_rejects_distinct_suffix(storage: str) -> None:
    """Distinct complete values still collide when their indexed prefixes match."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        title: mariadb.Col[str] = (
            mariadb.LongText() if storage == "longtext" else mariadb.Text()
        )
        __indexes__: ClassVar = [mariadb.Index(title, unique=True, prefix_lengths=(2,))]

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([Entry])})
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Entry(title="🐍a-first")))

        with assert_raises(mariadb.ExecutionError):
            async with database.transaction() as transaction:
                await transaction.execute(mariadb.insert(Entry(title="🐍a-other")))


@test(mark="slow")
async def prefix_counts_characters_not_bytes() -> None:
    """Distinct second characters remain distinct after a four-byte character."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        title: mariadb.Col[str] = mariadb.Text()
        __indexes__: ClassVar = [mariadb.Index(title, unique=True, prefix_lengths=(2,))]

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([Entry])})
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Entry(title="🐍a")))
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Entry(title="🐍b")))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(mariadb.select(Entry.title))

    assert_eq(sorted(rows), ["🐍a", "🐍b"])


@test(
    [
        Param(value=case, name=case)
        for case in ("length", "order", "unique", "missing", "full")
    ],
    mark="slow",
)
async def changed_prefix_index_is_drift(case: str) -> None:
    """Independent catalog changes cannot certify the declared index."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        tenant_id: mariadb.Col[int] = mariadb.Integer()
        title: mariadb.Col[str] = mariadb.Text()
        __indexes__: ClassVar = [
            mariadb.Index(tenant_id, title, prefix_lengths=(None, 3), name="ix_title")
        ]

    definitions = {
        "length": "INDEX ix_title (tenant_id, title(4))",
        "order": "INDEX ix_title (title(3), tenant_id)",
        "unique": "UNIQUE INDEX ix_title (tenant_id, title(3))",
        "missing": "",
        "full": "INDEX ix_title (tenant_id, title)",
    }
    index_sql = ", " + definitions[case] if definitions[case] else ""
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": f"CREATE TABLE entry (tenant_id BIGINT NOT NULL, title VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL{index_sql}) ENGINE=InnoDB"
            }
        )
        with assert_raises(mariadb.SchemaVerificationError) as caught:
            await database.verify([Entry])

    kind = {
        "length": "index.prefix_lengths",
        "order": "index.columns",
        "unique": "index.unique",
        "missing": "index.presence",
        "full": "index.prefix_lengths",
    }[case]
    assert_eq(
        [fact.status for fact in caught.exception.result.facts if fact.kind == kind],
        ["drift"],
    )


@test(mark="slow")
async def prefix_at_varchar_capacity_verifies() -> None:
    """A prefix equal to the declared VARCHAR capacity remains representable."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        title: mariadb.Col[str] = mariadb.Text(length=3)
        __indexes__: ClassVar = [mariadb.Index(title, prefix_lengths=(3,))]

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([Entry])})
        report = await database.verify([Entry])

    assert_eq(report.issues, ())


@test(mark="fast")
def prefix_declaration_is_frozen() -> None:
    """The declaration cannot change its prefix tuple after construction."""

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        title: mariadb.Col[str] = mariadb.Text()

    index = mariadb.Index(Entry.title, prefix_lengths=(3,))
    with assert_raises(FrozenInstanceError):
        index.prefix_lengths = (4,)  # ty: ignore[invalid-assignment]


@test(mark="fast")
def index_list_is_snapshotted() -> None:
    """Mutating the original declaration list cannot erase a bound prefix index."""

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        title: mariadb.Col[str] = mariadb.Text()
        __indexes__: ClassVar = [mariadb.Index(title, prefix_lengths=(3,))]

    Entry.__indexes__.clear()

    assert_in("ON `entry` (`title`(3))", mariadb.scaffold([Entry]))


@test(mark="fast")
def duplicate_prefixes_are_rejected() -> None:
    """Different names do not bypass duplicate declared index-member validation."""
    with assert_raises(mariadb.ModelDeclarationError):

        class Entry[S = mariadb.Pending](mariadb.Model[S]):
            __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
            title: mariadb.Col[str] = mariadb.Text()
            __indexes__: ClassVar = [
                mariadb.Index(title, prefix_lengths=(3,), name="first"),
                mariadb.Index(title, prefix_lengths=(3,), name="second"),
            ]


@test(mark="fast")
def all_full_prefixes_duplicate_ordinary_index() -> None:
    """Explicit None entries mean exactly the same full-column index as omission."""
    with assert_raises(mariadb.ModelDeclarationError):

        class Entry[S = mariadb.Pending](mariadb.Model[S]):
            __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
            title: mariadb.Col[str] = mariadb.Text()
            __indexes__: ClassVar = [
                mariadb.Index(title, name="first"),
                mariadb.Index(title, prefix_lengths=(None,), name="second"),
            ]


@test(mark="fast")
def full_unique_beside_prefix_remains_fk_target() -> None:
    """An additional prefix index cannot invalidate independent full uniqueness."""

    class Parent[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Parent[mariadb.Row]]]
        title: mariadb.Col[str] = mariadb.Text(unique=True)
        __indexes__: ClassVar = [mariadb.Index(title, prefix_lengths=(3,))]

    class Child[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Child[mariadb.Row]]]
        title: mariadb.FKCol[Parent, str] = mariadb.ForeignKey(Parent.title)

    assert_in("REFERENCES `parent` (`title`)", mariadb.scaffold([Parent, Child]))


@test(mark="fast")
def full_length_prefix_is_still_not_fk_candidate() -> None:
    """An explicit prefix is conservatively excluded even at VARCHAR capacity."""

    class Parent[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Parent[mariadb.Row]]]
        title: mariadb.Col[str] = mariadb.Text(length=3)
        __indexes__: ClassVar = [mariadb.Index(title, unique=True, prefix_lengths=(3,))]

    with assert_raises(mariadb.ModelDeclarationError):

        class Child[S = mariadb.Pending](mariadb.Model[S]):
            __row_type__: ClassVar[mariadb.ReadType[Child[mariadb.Row]]]
            title: mariadb.Col[str] = mariadb.Text(length=3)
            __foreign_keys__: ClassVar = [
                mariadb.ForeignKeyConstraint(title, references=(Parent.title,))
            ]


@test(
    [Param(value="varchar", name="varchar"), Param(value="longtext", name="longtext")],
    mark="slow",
)
async def prefix_does_not_truncate_stored_text(storage: str) -> None:
    """Indexing a short prefix does not shorten the row value or its codec limit."""
    server = await load_fixture(provide_mariadb_server())

    class Entry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
        title: mariadb.Col[str] = (
            mariadb.LongText() if storage == "longtext" else mariadb.Text(length=1000)
        )
        __indexes__: ClassVar = [mariadb.Index(title, prefix_lengths=(3,))]

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([Entry])})
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Entry(title="🐍" * 300)))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(mariadb.select(Entry.title))

    assert_eq(rows, ["🐍" * 300])


@test(mark="fast")
def prefix_cannot_exceed_long_text_capacity() -> None:
    """An impossible LONGTEXT character count fails without formatting huge SQL."""
    with assert_raises(mariadb.ModelDeclarationError):

        class Entry[S = mariadb.Pending](mariadb.Model[S]):
            __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
            title: mariadb.Col[str] = mariadb.LongText()
            __indexes__: ClassVar = [mariadb.Index(title, prefix_lengths=(2**20000,))]
