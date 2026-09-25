"""SQLite partial indexes through declarations, native writes, and verification."""

from collections.abc import AsyncGenerator
from gc import collect
from typing import Any, ClassVar, Self
from warnings import catch_warnings

from pydantic import Json
from snektest import Param, assert_eq, assert_in, assert_raises, test

from snekql import mariadb, sqlite


@test(mark="fast")
def partial_index_factory_scaffolds() -> None:
    """Bound-column predicates produce a named unique partial index."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        email: sqlite.Col[str] = sqlite.Text()
        active: sqlite.Col[bool] = sqlite.Integer()

        @classmethod
        def __indexes__(cls: type[Account[S]]) -> list[sqlite.Index[Account[S]]]:
            return [
                sqlite.Index(
                    cls.email,
                    unique=True,
                    where=cls.active.eq(True),
                    name="ux_active_email",
                )
            ]

    assert_in(
        'CREATE UNIQUE INDEX "ux_active_email" ON "account" ("email") WHERE "active" = 1',
        sqlite.scaffold([Account]),
    )


@test(mark="medium")
async def matching_hand_created_predicate_verifies() -> None:
    """Predicate structure is verified, not merely the partial-index flag."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        email: sqlite.Col[str] = sqlite.Text()
        active: sqlite.Col[bool] = sqlite.Integer()

        @classmethod
        def __indexes__(cls: type[Account[S]]) -> list[sqlite.Index[Account[S]]]:
            return [
                sqlite.Index(
                    cls.email,
                    unique=True,
                    where=cls.active.eq(True),
                    name="ux_active_email",
                )
            ]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE account (email TEXT NOT NULL, active INTEGER NOT NULL) STRICT; CREATE UNIQUE INDEX ux_active_email ON account (email) WHERE ((active == +01));"
            }
        )
        report = await database.verify([Account])

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "index.predicate"],
        ["matched"],
    )


@test(mark="fast")
def mariadb_rejects_partial_declaration() -> None:
    """A MariaDB declaration cannot accidentally emit SQLite partial-index SQL."""
    with assert_raises(mariadb.ModelDeclarationError):

        class Entry[S = mariadb.Pending](mariadb.Model[S]):
            __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
            label: mariadb.Col[str] = mariadb.Text()

            @classmethod
            def __indexes__(cls: type[Entry[S]]) -> list[mariadb.Index[Entry[S]]]:
                return [mariadb.Index(cls.label, where=cls.label.eq("active"))]


@test(mark="fast")
def partial_unique_cannot_authorize_scalar_fk() -> None:
    """Uniqueness over selected rows does not make a complete candidate key."""

    class Parent[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Parent[sqlite.Row]]]
        label: sqlite.Col[str] = sqlite.Text()

        @classmethod
        def __indexes__(cls: type[Parent[S]]) -> list[sqlite.Index[Parent[S]]]:
            return [sqlite.Index(cls.label, unique=True, where=cls.label.ne(""))]

    class Child[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Child[sqlite.Row]]]
        label: sqlite.FKCol[Parent, str] = sqlite.ForeignKey(Parent.label)

    with assert_raises(sqlite.SchemaError):
        sqlite.scaffold([Parent, Child])


@test(mark="fast")
def partial_unique_cannot_authorize_table_fk() -> None:
    """Table-level foreign keys require uniqueness for every possible target row."""

    class Parent[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Parent[sqlite.Row]]]
        label: sqlite.Col[str] = sqlite.Text()

        @classmethod
        def __indexes__(cls: type[Parent[S]]) -> list[sqlite.Index[Parent[S]]]:
            return [sqlite.Index(cls.label, unique=True, where=cls.label.ne(""))]

    with assert_raises(sqlite.ModelDeclarationError):

        class Child[S = sqlite.Pending](sqlite.Model[S]):
            __row_type__: ClassVar[sqlite.ReadType[Child[sqlite.Row]]]
            label: sqlite.Col[str] = sqlite.Text()
            __foreign_keys__: ClassVar = [
                sqlite.ForeignKeyConstraint(label, references=(Parent.label,))
            ]


@test(mark="fast")
def distinct_predicates_can_share_columns() -> None:
    """Named full and distinct partial indexes retain the same indexed columns."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        label: sqlite.Col[str] = sqlite.Text()
        status: sqlite.Col[int] = sqlite.Integer()

        @classmethod
        def __indexes__(cls: type[Entry[S]]) -> list[sqlite.Index[Entry[S]]]:
            return [
                sqlite.Index(cls.label, name="ix_full"),
                sqlite.Index(cls.label, where=cls.status.eq(1), name="ix_one"),
                sqlite.Index(cls.label, where=cls.status.eq(2), name="ix_two"),
            ]

    assert_eq(sqlite.scaffold([Entry]).count("CREATE INDEX"), 3)


@test(mark="fast")
def self_typed_index_factory() -> None:
    """Self keeps descriptor ownership exact without annotating cls explicitly."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        label: sqlite.Col[str] = sqlite.Text()

        @classmethod
        def __indexes__(cls) -> list[sqlite.Index[Self]]:
            return [sqlite.Index(cls.label, where=cls.label.ne(""))]

    assert_in('WHERE "label" <>', sqlite.scaffold([Entry]))


@test(mark="medium")
async def unique_partial_insert_collision() -> None:
    """Two rows in the selected subset cannot share a unique indexed value."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        label: sqlite.Col[str] = sqlite.Text()
        active: sqlite.Col[bool | None] = sqlite.Integer()

        @classmethod
        def __indexes__(cls) -> list[sqlite.Index[Self]]:
            return [sqlite.Index(cls.label, unique=True, where=cls.active.eq(True))]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate({"001": sqlite.scaffold([Entry])})
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(Entry(label="same", active=True)))

        with assert_raises(sqlite.ExecutionError):
            async with database.transaction() as transaction:
                await transaction.execute(
                    sqlite.insert(Entry(label="same", active=True))
                )


@test([Param(value=False, name="false"), Param(value=None, name="null")], mark="medium")
async def excluded_rows_can_duplicate(active: bool | None) -> None:  # noqa: FBT001
    """SQL false and unknown both exclude a row from the unique index."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        label: sqlite.Col[str] = sqlite.Text()
        active: sqlite.Col[bool | None] = sqlite.Integer()

        @classmethod
        def __indexes__(cls) -> list[sqlite.Index[Self]]:
            return [sqlite.Index(cls.label, unique=True, where=cls.active.eq(True))]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate({"001": sqlite.scaffold([Entry])})
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(Entry(label="same", active=True)))
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(Entry(label="same", active=active)))
            await transaction.execute(sqlite.insert(Entry(label="same", active=active)))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(sqlite.select(Entry.label).all())

    assert_eq(rows, ["same", "same", "same"])


@test(mark="medium")
async def update_into_subset_enforces_uniqueness() -> None:
    """Changing the predicate column checks uniqueness even when it is not indexed."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        number: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        label: sqlite.Col[str] = sqlite.Text()
        active: sqlite.Col[bool] = sqlite.Integer()

        @classmethod
        def __indexes__(cls) -> list[sqlite.Index[Self]]:
            return [sqlite.Index(cls.label, unique=True, where=cls.active.eq(True))]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate({"001": sqlite.scaffold([Entry])})
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.insert(Entry(number=1, label="same", active=True))
            )
            await transaction.execute(
                sqlite.insert(Entry(number=2, label="same", active=False))
            )

        with assert_raises(sqlite.ExecutionError):
            async with database.transaction() as transaction:
                await transaction.execute(
                    sqlite.update(Entry)
                    .set(Entry.active.to(True))
                    .where(Entry.number.eq(2))
                )


@test(
    [
        Param(value=case, name=case)
        for case in ("changed", "full", "arithmetic", "function", "null", "comment")
    ],
    mark="medium",
)
async def catalog_predicate_classification(case: str) -> None:
    """Known differences drift; unsupported SQL never becomes a match."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        label: sqlite.Col[str] = sqlite.Text()
        active: sqlite.Col[int] = sqlite.Integer()

        @classmethod
        def __indexes__(cls) -> list[sqlite.Index[Self]]:
            return [sqlite.Index(cls.label, where=cls.active.eq(1), name="ix_active")]

    clauses = {
        "changed": "WHERE active = 2",
        "full": "",
        "arithmetic": "WHERE active + 0 = 1",
        "function": "WHERE abs(active) = 1",
        "null": "WHERE active = NULL",
        "comment": '/* WHERE ignored */ WHERE (("active" == +01)) -- tail',
    }
    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE entry (label TEXT NOT NULL, active INTEGER NOT NULL) STRICT; CREATE INDEX ix_active ON entry(label) "
                + clauses[case]
                + "\n;"
            }
        )
        report = await database.verify([Entry], policy="warn")

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "index.predicate"],
        [
            {
                "changed": "drift",
                "full": "drift",
                "arithmetic": "unchecked",
                "function": "unchecked",
                "null": "unchecked",
                "comment": "matched",
            }[case]
        ],
    )


@test(mark="fast")
def index_factory_runs_once() -> None:
    """Scaffold consumes the bound snapshot instead of rerunning application code."""
    calls: list[str] = []

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        label: sqlite.Col[str] = sqlite.Text()

        @classmethod
        def __indexes__(cls) -> list[sqlite.Index[Self]]:
            calls.append("called")
            return [sqlite.Index(cls.label, where=cls.label.ne(""))]

    sqlite.scaffold([Entry])
    sqlite.scaffold([Entry])

    assert_eq(calls, ["called"])


@test(mark="fast")
def asynchronous_factory_is_rejected_before_start() -> None:
    """An async declaration never creates an unawaited coroutine."""
    with catch_warnings(record=True) as warnings:
        with assert_raises(sqlite.ModelDeclarationError):

            class Entry[S = sqlite.Pending](sqlite.Model[S]):
                __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
                label: sqlite.Col[str] = sqlite.Text()

                @classmethod
                async def __indexes__(cls) -> list[sqlite.Index[Self]]:
                    return [sqlite.Index(cls.label, where=cls.label.ne(""))]

        collect()
    assert_eq(warnings, [])


@test(mark="fast")
def factory_sees_frozen_columns() -> None:
    """The callback cannot rewrite column metadata used by its predicates."""
    with assert_raises(sqlite.FrozenModelError):

        class Entry[S = sqlite.Pending](sqlite.Model[S]):
            __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
            label: sqlite.Col[str] = sqlite.Text()

            @classmethod
            def __indexes__(cls) -> list[sqlite.Index[Self]]:
                cls.label.text_collation = "NOCASE"
                return []


@test(mark="medium")
async def escaped_predicate_round_trips() -> None:
    """Backslashes, quotes, NUL, and SQL-looking text stay literal data."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        label: sqlite.Col[str] = sqlite.Text()

        @classmethod
        def __indexes__(cls) -> list[sqlite.Index[Self]]:
            return [sqlite.Index(cls.label, where=cls.label.eq("'\\\0 WHERE --é"))]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate({"001": sqlite.scaffold([Entry])})
        report = await database.verify([Entry])

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "index.predicate"],
        ["matched"],
    )


@test(
    [
        Param(value=case, name=case)
        for case in (
            "raw",
            "boolean",
            "foreign",
            "arithmetic",
            "json",
            "real",
            "unicode",
        )
    ],
    mark="fast",
)
def unsupported_predicate_fails_before_io(case: str) -> None:
    """Only bounded local predicates and codec-valid literals can enter DDL."""

    class Other[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Other[sqlite.Row]]]
        number: sqlite.Col[int] = sqlite.Integer()

    with assert_raises(sqlite.ModelDeclarationError):

        class Entry[S = sqlite.Pending](sqlite.Model[S]):
            __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
            number: sqlite.Col[int] = sqlite.Integer()
            label: sqlite.Col[str] = sqlite.Text()
            encoded: sqlite.Col[Json[str]] = sqlite.Text()
            real: sqlite.Col[float] = sqlite.Real()

            @classmethod
            def __indexes__(cls) -> list[sqlite.Index[Self]]:
                predicate: Any
                match case:
                    case "raw":
                        predicate = "number > 0"
                    case "boolean":
                        predicate = True
                    case "foreign":
                        predicate = Other.number.eq(1)
                    case "arithmetic":
                        predicate = cls.number.add(1).eq(2)
                    case "json":
                        predicate = cls.encoded.eq("a")
                    case "real":
                        predicate = cls.real.eq(1.0)
                    case _:
                        predicate = cls.label.eq("\ud800")
                return [sqlite.Index(cls.number, where=predicate)]  # ty: ignore[invalid-argument-type]


@test(mark="fast")
def full_unique_beside_partial_authorizes_fk() -> None:
    """Independent full uniqueness remains available to foreign-key validation."""

    class Parent[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Parent[sqlite.Row]]]
        label: sqlite.Col[str] = sqlite.Text(unique=True)

        @classmethod
        def __indexes__(cls) -> list[sqlite.Index[Self]]:
            return [sqlite.Index(cls.label, where=cls.label.ne(""), name="ix_selected")]

    class Child[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Child[sqlite.Row]]]
        label: sqlite.FKCol[Parent, str] = sqlite.ForeignKey(Parent.label)

    assert_in('REFERENCES "parent" ("label")', sqlite.scaffold([Parent, Child]))


@test(mark="fast")
def invalid_factory_return_is_rejected() -> None:
    """The callback returns a list, not an arbitrary iterable."""
    with assert_raises(sqlite.ModelDeclarationError):

        class Entry[S = sqlite.Pending](sqlite.Model[S]):
            __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
            label: sqlite.Col[str] = sqlite.Text()

            @classmethod
            def __indexes__(cls) -> tuple[sqlite.Index[Self]]:
                return (sqlite.Index(cls.label),)


@test(mark="medium")
async def sqlite_identifier_case_normalizes() -> None:
    """ASCII identifier case changes do not change a partial predicate's column."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        label: sqlite.Col[str] = sqlite.Text()
        active: sqlite.Col[int] = sqlite.Integer()

        @classmethod
        def __indexes__(cls) -> list[sqlite.Index[Self]]:
            return [sqlite.Index(cls.label, where=cls.active.eq(1), name="ix_active")]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": 'CREATE TABLE entry (label TEXT NOT NULL, active INTEGER NOT NULL) STRICT; CREATE INDEX ix_active ON entry(label) WHERE "ACTIVE" = 1;'
            }
        )
        report = await database.verify([Entry])

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "index.predicate"],
        ["matched"],
    )


@test(mark="medium")
async def unknown_quoted_operand_is_unchecked() -> None:
    """SQLite's double-quoted string fallback is not a fabricated column match."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        label: sqlite.Col[str] = sqlite.Text()

        @classmethod
        def __indexes__(cls) -> list[sqlite.Index[Self]]:
            return [
                sqlite.Index(
                    cls.label, where=cls.label.eq("missing"), name="ix_selected"
                )
            ]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": 'CREATE TABLE entry (label TEXT NOT NULL) STRICT; CREATE INDEX ix_selected ON entry(label) WHERE label = "missing";'
            }
        )
        report = await database.verify([Entry])

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "index.predicate"],
        ["unchecked"],
    )


@test(mark="medium")
async def quoted_where_names_do_not_hide_predicate() -> None:
    """WHERE inside a name or string does not identify the predicate delimiter."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        where: sqlite.Col[str] = sqlite.Text()

        @classmethod
        def __indexes__(cls) -> list[sqlite.Index[Self]]:
            return [sqlite.Index(cls.where, where=cls.where.eq("WHERE"), name="where")]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate({"001": sqlite.scaffold([Entry])})
        report = await database.verify([Entry])

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "index.predicate"],
        ["matched"],
    )


@test(mark="fast")
def declaration_list_is_snapshotted() -> None:
    """Changing a returned list does not change an already bound schema predicate."""
    captured: list[Any] = []

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        label: sqlite.Col[str] = sqlite.Text()

        @classmethod
        def __indexes__(cls) -> list[sqlite.Index[Self]]:
            declarations = [sqlite.Index(cls.label, where=cls.label.ne(""))]
            captured.append(declarations)
            return declarations

    captured[0].clear()

    assert_in('WHERE "label" <>', sqlite.scaffold([Entry]))


@test(mark="fast")
def async_generator_factory_is_not_started() -> None:
    """An async generator cannot stand in for a synchronous declaration list."""
    calls: list[str] = []
    with assert_raises(sqlite.ModelDeclarationError):

        class Entry[S = sqlite.Pending](sqlite.Model[S]):
            __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
            label: sqlite.Col[str] = sqlite.Text()

            @classmethod
            async def __indexes__(cls) -> AsyncGenerator[sqlite.Index[Self]]:
                calls.append("called")
                yield sqlite.Index(cls.label)

    assert_eq(calls, [])


@test(mark="medium")
async def unsupported_predicate_does_not_fail_strict_verification() -> None:
    """An unchecked predicate is not silently promoted to either match or drift."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        number: sqlite.Col[int] = sqlite.Integer()

        @classmethod
        def __indexes__(cls) -> list[sqlite.Index[Self]]:
            return [
                sqlite.Index(cls.number, where=cls.number.eq(1), name="ix_selected")
            ]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE entry(number INTEGER NOT NULL) STRICT; CREATE INDEX ix_selected ON entry(number) WHERE abs(number) = 1;"
            }
        )
        report = await database.verify([Entry])

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "index.predicate"],
        ["unchecked"],
    )


@test(mark="medium")
async def changed_predicate_fails_strict_verification() -> None:
    """Strict verification rejects a recognized, structurally different predicate."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        number: sqlite.Col[int] = sqlite.Integer()

        @classmethod
        def __indexes__(cls) -> list[sqlite.Index[Self]]:
            return [
                sqlite.Index(cls.number, where=cls.number.eq(1), name="ix_selected")
            ]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE entry(number INTEGER NOT NULL) STRICT; CREATE INDEX ix_selected ON entry(number) WHERE number = 2;"
            }
        )
        with assert_raises(sqlite.SchemaVerificationError):
            await database.verify([Entry])


@test(mark="medium")
async def column_only_upsert_does_not_target_partial_uniqueness() -> None:
    """Schema support does not invent an ON CONFLICT target predicate."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        number: sqlite.Col[int] = sqlite.Integer()

        @classmethod
        def __indexes__(cls) -> list[sqlite.Index[Self]]:
            return [sqlite.Index(cls.number, unique=True, where=cls.number.gt(0))]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate({"001": sqlite.scaffold([Entry])})
        with assert_raises(sqlite.ExecutionError):
            async with database.transaction() as transaction:
                await transaction.execute(
                    sqlite.insert(Entry(number=1)).on_conflict(
                        Entry.number, action=sqlite.DoNothing
                    )
                )
