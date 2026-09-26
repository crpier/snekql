"""Table-level foreign keys through declaration, scaffold, and database interfaces."""

from dataclasses import FrozenInstanceError
from decimal import Decimal
from typing import Any, ClassVar

from snektest import Param, assert_eq, assert_in, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import provide_mariadb_server


@test(mark="fast")
def composite_constraint_scaffold_preserves_pair_order() -> None:
    """One ordered relationship emits one SQL constraint."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        tenant_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        id: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        tenant_id: sqlite.Col[int] = sqlite.Integer()
        account_id: sqlite.Col[int] = sqlite.Integer()
        __foreign_keys__: ClassVar = [
            sqlite.ForeignKeyConstraint(
                tenant_id,
                account_id,
                references=(Account.tenant_id, Account.id),
                on_delete="CASCADE",
            )
        ]

    assert_in(
        'FOREIGN KEY ("tenant_id", "account_id") REFERENCES "account" ("tenant_id", "id") ON DELETE CASCADE',
        sqlite.scaffold([Account, Entry]),
    )


@test(
    [
        Param(value=value, name=value)
        for value in (
            "empty",
            "arity",
            "repeated-local",
            "repeated-target",
            "local-not-column",
            "target-not-column",
            "references-list",
            "bad-delete",
            "bad-update",
            "unkeyable",
        )
    ],
    mark="fast",
)
def malformed_constraint_is_rejected(problem: str) -> None:  # noqa: C901
    """Reject malformed declarations before model binding or database access."""
    local = sqlite.Integer()
    target = sqlite.Integer()
    columns: tuple[Any, ...] = (local,)
    references: Any = (target,)
    options: dict[str, Any] = {}
    if problem == "empty":
        columns, references = (), ()
    elif problem == "arity":
        references = (target, sqlite.Integer())
    elif problem == "repeated-local":
        columns, references = (local, local), (target, sqlite.Integer())
    elif problem == "repeated-target":
        columns, references = (local, sqlite.Integer()), (target, target)
    elif problem == "local-not-column":
        columns = ("local",)
    elif problem == "target-not-column":
        references = ("target",)
    elif problem == "references-list":
        references = [target]
    elif problem == "bad-delete":
        options["on_delete"] = "SET DEFAULT"
    elif problem == "bad-update":
        options["on_update"] = "cascade"
    elif problem == "unkeyable":
        columns = (mariadb.LongText(),)

    with assert_raises(sqlite.ModelDeclarationError):
        sqlite.ForeignKeyConstraint(*columns, references=references, **options)  # ty: ignore[invalid-argument-type]


@test(
    [
        Param(value=value, name=value)
        for value in (
            "not-list",
            "not-constraint",
            "foreign-local",
            "mixed-targets",
            "unbound-target",
            "nonunique-target",
            "incomplete-key",
            "reversed-key",
            "backend",
            "storage",
            "set-null",
        )
    ],
    mark="fast",
)
def invalid_bound_constraint_is_rejected(problem: str) -> None:  # noqa: C901
    """Model binding fixes ownership, storage, candidate-key, and action contracts."""

    class Parent[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Parent[sqlite.Row]]]
        first: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        second: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        ordinary: sqlite.Col[int] = sqlite.Integer()

    class Other[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Other[mariadb.Row]]]
        first: mariadb.Col[int] = mariadb.Integer(primary_key=True)

    class Foreign[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Foreign[sqlite.Row]]]
        second: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    with assert_raises(sqlite.ModelDeclarationError):

        class Child[S = sqlite.Pending](sqlite.Model[S]):
            __row_type__: ClassVar[sqlite.ReadType[Child[sqlite.Row]]]
            first: sqlite.Col[int] = sqlite.Integer()
            second: sqlite.Col[int] = sqlite.Integer()
            __foreign_keys__: ClassVar[Any] = [
                sqlite.ForeignKeyConstraint(
                    first, second, references=(Parent.first, Parent.second)
                )
            ]
            if problem == "not-list":
                __foreign_keys__ = tuple(__foreign_keys__)
            elif problem == "not-constraint":
                __foreign_keys__ = ["constraint"]
            elif problem == "foreign-local":
                __foreign_keys__ = [
                    sqlite.ForeignKeyConstraint(
                        Foreign.second, references=(Foreign.second,)
                    )
                ]
            elif problem == "mixed-targets":
                __foreign_keys__ = [
                    sqlite.ForeignKeyConstraint(
                        first,
                        second,
                        references=(Parent.first, Foreign.second),  # ty: ignore[invalid-argument-type]
                    )
                ]
            elif problem == "unbound-target":
                __foreign_keys__ = [
                    sqlite.ForeignKeyConstraint(first, references=(sqlite.Integer(),))
                ]
            elif problem == "nonunique-target":
                __foreign_keys__ = [
                    sqlite.ForeignKeyConstraint(first, references=(Parent.ordinary,))
                ]
            elif problem == "incomplete-key":
                __foreign_keys__ = [
                    sqlite.ForeignKeyConstraint(first, references=(Parent.first,))
                ]
            elif problem == "reversed-key":
                __foreign_keys__ = [
                    sqlite.ForeignKeyConstraint(
                        first, second, references=(Parent.second, Parent.first)
                    )
                ]
            elif problem == "backend":
                __foreign_keys__ = [
                    sqlite.ForeignKeyConstraint(first, references=(Other.first,))
                ]
            elif problem == "storage":
                first = sqlite.Text()
                __foreign_keys__ = [
                    sqlite.ForeignKeyConstraint(
                        first, second, references=(Parent.first, Parent.second)
                    )
                ]
            elif problem == "set-null":
                __foreign_keys__ = [
                    sqlite.ForeignKeyConstraint(
                        first,
                        second,
                        references=(Parent.first, Parent.second),
                        on_delete="SET NULL",
                    )
                ]


@test(
    [Param(value=True, name="composite"), Param(value=False, name="split-scalars")],
    mark="medium",
)
async def sqlite_verification_compares_constraint_grouping(composite: bool) -> None:  # noqa: FBT001
    """Identical flattened pairs must not hide a split composite relationship."""

    class Parent[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Parent[sqlite.Row]]]
        first: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        second: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    class Child[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Child[sqlite.Row]]]
        first: sqlite.Col[int] = sqlite.Integer()
        second: sqlite.Col[int] = sqlite.Integer()
        __foreign_keys__: ClassVar = [
            sqlite.ForeignKeyConstraint(
                first, second, references=(Parent.first, Parent.second)
            )
        ]

    constraint = (
        "FOREIGN KEY(first, second) REFERENCES parent(first, second)"
        if composite
        else "FOREIGN KEY(first) REFERENCES parent(first), FOREIGN KEY(second) REFERENCES parent(second)"
    )
    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": f"CREATE TABLE parent (first INTEGER NOT NULL UNIQUE, second INTEGER NOT NULL UNIQUE, PRIMARY KEY(first, second)) STRICT; CREATE TABLE child (first INTEGER NOT NULL, second INTEGER NOT NULL, {constraint}) STRICT"
            }
        )
        report = await database.verify([Child], policy="warn")

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "foreign_keys.grouping"],
        ["matched" if composite else "drift"],
    )
    assert_eq(bool(report.issues), not composite)


@test(
    [Param(value=True, name="composite"), Param(value=False, name="split-scalars")],
    mark="slow",
)
async def mariadb_verification_compares_constraint_grouping(composite: bool) -> None:  # noqa: FBT001
    """Identical flattened pairs must not hide a split composite relationship."""
    server = await load_fixture(provide_mariadb_server())

    class Parent[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Parent[mariadb.Row]]]
        first: mariadb.Col[int] = mariadb.Integer(primary_key=True)
        second: mariadb.Col[int] = mariadb.Integer(primary_key=True)

    class Child[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Child[mariadb.Row]]]
        first: mariadb.Col[int] = mariadb.Integer()
        second: mariadb.Col[int] = mariadb.Integer()
        __foreign_keys__: ClassVar = [
            mariadb.ForeignKeyConstraint(
                first, second, references=(Parent.first, Parent.second)
            )
        ]

    constraint = (
        "FOREIGN KEY(first, second) REFERENCES parent(first, second)"
        if composite
        else "FOREIGN KEY(first) REFERENCES parent(first), FOREIGN KEY(second) REFERENCES parent(second)"
    )
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": f"CREATE TABLE parent (first BIGINT NOT NULL UNIQUE, second BIGINT NOT NULL UNIQUE, PRIMARY KEY(first, second)) ENGINE=InnoDB; CREATE TABLE child (first BIGINT NOT NULL, second BIGINT NOT NULL, {constraint}) ENGINE=InnoDB"
            }
        )
        report = await database.verify([Child], policy="warn")

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "foreign_keys.grouping"],
        ["matched" if composite else "drift"],
    )
    assert_eq(bool(report.issues), not composite)


@test(
    [Param(value="primary", name="primary"), Param(value="unique", name="unique")],
    mark="medium",
)
async def sqlite_rejects_mixed_parent_rows(key: str) -> None:
    """No pair may combine key members from two different parent rows."""

    class Parent[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Parent[sqlite.Row]]]
        first: sqlite.Col[int] = sqlite.Integer(primary_key=key == "primary")
        second: sqlite.Col[int] = sqlite.Integer(primary_key=key == "primary")
        __indexes__: ClassVar = (
            [] if key == "primary" else [sqlite.Index(first, second, unique=True)]
        )

    class Child[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Child[sqlite.Row]]]
        first: sqlite.Col[int | None] = sqlite.Integer(nullable=True)
        second: sqlite.Col[int | None] = sqlite.Integer(nullable=True)
        __foreign_keys__: ClassVar = [
            sqlite.ForeignKeyConstraint(
                first,
                second,
                references=(Parent.first, Parent.second),
                on_delete="CASCADE",
                on_update="CASCADE",
            )
        ]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": sqlite.scaffold([Parent, Child])
                + "INSERT INTO parent VALUES (1, 10), (2, 20)"
            }
        )
        with assert_raises(sqlite.ExecutionError):
            async with database.transaction() as transaction:
                await transaction.execute(sqlite.insert(Child(first=1, second=20)))


@test(
    [Param(value="primary", name="primary"), Param(value="unique", name="unique")],
    mark="medium",
)
async def sqlite_allows_nullable_partial_keys(key: str) -> None:
    """A NULL member bypasses the default composite relationship check."""

    class Parent[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Parent[sqlite.Row]]]
        first: sqlite.Col[int] = sqlite.Integer(primary_key=key == "primary")
        second: sqlite.Col[int] = sqlite.Integer(primary_key=key == "primary")
        __indexes__: ClassVar = (
            [] if key == "primary" else [sqlite.Index(first, second, unique=True)]
        )

    class Child[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Child[sqlite.Row]]]
        first: sqlite.Col[int | None] = sqlite.Integer(nullable=True)
        second: sqlite.Col[int | None] = sqlite.Integer(nullable=True)
        __foreign_keys__: ClassVar = [
            sqlite.ForeignKeyConstraint(
                first,
                second,
                references=(Parent.first, Parent.second),
                on_delete="CASCADE",
                on_update="CASCADE",
            )
        ]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": sqlite.scaffold([Parent, Child])
                + "INSERT INTO parent VALUES (1, 10), (2, 20)"
            }
        )
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(Child(first=None, second=999)))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(sqlite.select(Child.first, Child.second))

    assert_eq(rows, [(None, 999)])


@test(
    [Param(value="primary", name="primary"), Param(value="unique", name="unique")],
    mark="medium",
)
async def sqlite_cascades_parent_deletion(key: str) -> None:
    """Deleting the referenced pair removes its child row."""

    class Parent[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Parent[sqlite.Row]]]
        first: sqlite.Col[int] = sqlite.Integer(primary_key=key == "primary")
        second: sqlite.Col[int] = sqlite.Integer(primary_key=key == "primary")
        __indexes__: ClassVar = (
            [] if key == "primary" else [sqlite.Index(first, second, unique=True)]
        )

    class Child[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Child[sqlite.Row]]]
        first: sqlite.Col[int | None] = sqlite.Integer(nullable=True)
        second: sqlite.Col[int | None] = sqlite.Integer(nullable=True)
        __foreign_keys__: ClassVar = [
            sqlite.ForeignKeyConstraint(
                first,
                second,
                references=(Parent.first, Parent.second),
                on_delete="CASCADE",
                on_update="CASCADE",
            )
        ]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": sqlite.scaffold([Parent, Child])
                + "INSERT INTO parent VALUES (1, 10), (2, 20); INSERT INTO child VALUES (1, 10)"
            }
        )
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.delete(Parent).where(Parent.first.eq(1)))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(sqlite.select(Child.first, Child.second))

    assert_eq(rows, [])


@test(
    [Param(value="primary", name="primary"), Param(value="unique", name="unique")],
    mark="medium",
)
async def sqlite_nulls_every_local_member(key: str) -> None:
    """SET NULL changes every local member of the composite relationship."""

    class Parent[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Parent[sqlite.Row]]]
        first: sqlite.Col[int] = sqlite.Integer(primary_key=key == "primary")
        second: sqlite.Col[int] = sqlite.Integer(primary_key=key == "primary")
        __indexes__: ClassVar = (
            [] if key == "primary" else [sqlite.Index(first, second, unique=True)]
        )

    class Child[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Child[sqlite.Row]]]
        first: sqlite.Col[int | None] = sqlite.Integer(nullable=True)
        second: sqlite.Col[int | None] = sqlite.Integer(nullable=True)
        __foreign_keys__: ClassVar = [
            sqlite.ForeignKeyConstraint(
                first,
                second,
                references=(Parent.first, Parent.second),
                on_delete="SET NULL",
                on_update="CASCADE",
            )
        ]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": sqlite.scaffold([Parent, Child])
                + "INSERT INTO parent VALUES (1, 10), (2, 20); INSERT INTO child VALUES (1, 10)"
            }
        )
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.delete(Parent).where(Parent.first.eq(1)))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(sqlite.select(Child.first, Child.second))

    assert_eq(rows, [(None, None)])


@test(
    [Param(value="primary", name="primary"), Param(value="unique", name="unique")],
    mark="medium",
)
async def sqlite_cascades_parent_key_update(key: str) -> None:
    """Updating a referenced key member updates the matching child pair."""

    class Parent[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Parent[sqlite.Row]]]
        first: sqlite.Col[int] = sqlite.Integer(primary_key=key == "primary")
        second: sqlite.Col[int] = sqlite.Integer(primary_key=key == "primary")
        __indexes__: ClassVar = (
            [] if key == "primary" else [sqlite.Index(first, second, unique=True)]
        )

    class Child[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Child[sqlite.Row]]]
        first: sqlite.Col[int | None] = sqlite.Integer(nullable=True)
        second: sqlite.Col[int | None] = sqlite.Integer(nullable=True)
        __foreign_keys__: ClassVar = [
            sqlite.ForeignKeyConstraint(
                first,
                second,
                references=(Parent.first, Parent.second),
                on_delete="CASCADE",
                on_update="CASCADE",
            )
        ]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": sqlite.scaffold([Parent, Child])
                + "INSERT INTO parent VALUES (1, 10), (2, 20); INSERT INTO child VALUES (1, 10)"
            }
        )
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.update(Parent)
                .set(Parent.second.to(11))
                .where(Parent.first.eq(1))
            )
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(sqlite.select(Child.first, Child.second))

    assert_eq(rows, [(1, 11)])


@test(
    [Param(value="primary", name="primary"), Param(value="unique", name="unique")],
    mark="slow",
)
async def mariadb_rejects_mixed_parent_rows(key: str) -> None:
    """No pair may combine key members from two different parent rows."""
    server = await load_fixture(provide_mariadb_server())

    class Parent[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Parent[mariadb.Row]]]
        first: mariadb.Col[int] = mariadb.Integer(primary_key=key == "primary")
        second: mariadb.Col[int] = mariadb.Integer(primary_key=key == "primary")
        __indexes__: ClassVar = (
            [] if key == "primary" else [mariadb.Index(first, second, unique=True)]
        )

    class Child[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Child[mariadb.Row]]]
        first: mariadb.Col[int | None] = mariadb.Integer(nullable=True)
        second: mariadb.Col[int | None] = mariadb.Integer(nullable=True)
        __foreign_keys__: ClassVar = [
            mariadb.ForeignKeyConstraint(
                first,
                second,
                references=(Parent.first, Parent.second),
                on_delete="CASCADE",
                on_update="CASCADE",
            )
        ]

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": mariadb.scaffold([Parent, Child])
                + "INSERT INTO parent VALUES (1, 10), (2, 20)"
            }
        )
        with assert_raises(mariadb.ExecutionError):
            async with database.transaction() as transaction:
                await transaction.execute(mariadb.insert(Child(first=1, second=20)))


@test(
    [Param(value="primary", name="primary"), Param(value="unique", name="unique")],
    mark="slow",
)
async def mariadb_allows_nullable_partial_keys(key: str) -> None:
    """A NULL member bypasses the default composite relationship check."""
    server = await load_fixture(provide_mariadb_server())

    class Parent[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Parent[mariadb.Row]]]
        first: mariadb.Col[int] = mariadb.Integer(primary_key=key == "primary")
        second: mariadb.Col[int] = mariadb.Integer(primary_key=key == "primary")
        __indexes__: ClassVar = (
            [] if key == "primary" else [mariadb.Index(first, second, unique=True)]
        )

    class Child[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Child[mariadb.Row]]]
        first: mariadb.Col[int | None] = mariadb.Integer(nullable=True)
        second: mariadb.Col[int | None] = mariadb.Integer(nullable=True)
        __foreign_keys__: ClassVar = [
            mariadb.ForeignKeyConstraint(
                first,
                second,
                references=(Parent.first, Parent.second),
                on_delete="CASCADE",
                on_update="CASCADE",
            )
        ]

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": mariadb.scaffold([Parent, Child])
                + "INSERT INTO parent VALUES (1, 10), (2, 20)"
            }
        )
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Child(first=None, second=999)))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(
                mariadb.select(Child.first, Child.second)
            )

    assert_eq(rows, [(None, 999)])


@test(
    [Param(value="primary", name="primary"), Param(value="unique", name="unique")],
    mark="slow",
)
async def mariadb_cascades_parent_deletion(key: str) -> None:
    """Deleting the referenced pair removes its child row."""
    server = await load_fixture(provide_mariadb_server())

    class Parent[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Parent[mariadb.Row]]]
        first: mariadb.Col[int] = mariadb.Integer(primary_key=key == "primary")
        second: mariadb.Col[int] = mariadb.Integer(primary_key=key == "primary")
        __indexes__: ClassVar = (
            [] if key == "primary" else [mariadb.Index(first, second, unique=True)]
        )

    class Child[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Child[mariadb.Row]]]
        first: mariadb.Col[int | None] = mariadb.Integer(nullable=True)
        second: mariadb.Col[int | None] = mariadb.Integer(nullable=True)
        __foreign_keys__: ClassVar = [
            mariadb.ForeignKeyConstraint(
                first,
                second,
                references=(Parent.first, Parent.second),
                on_delete="CASCADE",
                on_update="CASCADE",
            )
        ]

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": mariadb.scaffold([Parent, Child])
                + "INSERT INTO parent VALUES (1, 10), (2, 20); INSERT INTO child VALUES (1, 10)"
            }
        )
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.delete(Parent).where(Parent.first.eq(1)))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(
                mariadb.select(Child.first, Child.second)
            )

    assert_eq(rows, [])


@test(
    [Param(value="primary", name="primary"), Param(value="unique", name="unique")],
    mark="slow",
)
async def mariadb_nulls_every_local_member(key: str) -> None:
    """SET NULL changes every local member of the composite relationship."""
    server = await load_fixture(provide_mariadb_server())

    class Parent[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Parent[mariadb.Row]]]
        first: mariadb.Col[int] = mariadb.Integer(primary_key=key == "primary")
        second: mariadb.Col[int] = mariadb.Integer(primary_key=key == "primary")
        __indexes__: ClassVar = (
            [] if key == "primary" else [mariadb.Index(first, second, unique=True)]
        )

    class Child[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Child[mariadb.Row]]]
        first: mariadb.Col[int | None] = mariadb.Integer(nullable=True)
        second: mariadb.Col[int | None] = mariadb.Integer(nullable=True)
        __foreign_keys__: ClassVar = [
            mariadb.ForeignKeyConstraint(
                first,
                second,
                references=(Parent.first, Parent.second),
                on_delete="SET NULL",
                on_update="CASCADE",
            )
        ]

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": mariadb.scaffold([Parent, Child])
                + "INSERT INTO parent VALUES (1, 10), (2, 20); INSERT INTO child VALUES (1, 10)"
            }
        )
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.delete(Parent).where(Parent.first.eq(1)))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(
                mariadb.select(Child.first, Child.second)
            )

    assert_eq(rows, [(None, None)])


@test(
    [Param(value="primary", name="primary"), Param(value="unique", name="unique")],
    mark="slow",
)
async def mariadb_cascades_parent_key_update(key: str) -> None:
    """Updating a referenced key member updates the matching child pair."""
    server = await load_fixture(provide_mariadb_server())

    class Parent[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Parent[mariadb.Row]]]
        first: mariadb.Col[int] = mariadb.Integer(primary_key=key == "primary")
        second: mariadb.Col[int] = mariadb.Integer(primary_key=key == "primary")
        __indexes__: ClassVar = (
            [] if key == "primary" else [mariadb.Index(first, second, unique=True)]
        )

    class Child[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Child[mariadb.Row]]]
        first: mariadb.Col[int | None] = mariadb.Integer(nullable=True)
        second: mariadb.Col[int | None] = mariadb.Integer(nullable=True)
        __foreign_keys__: ClassVar = [
            mariadb.ForeignKeyConstraint(
                first,
                second,
                references=(Parent.first, Parent.second),
                on_delete="CASCADE",
                on_update="CASCADE",
            )
        ]

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": mariadb.scaffold([Parent, Child])
                + "INSERT INTO parent VALUES (1, 10), (2, 20); INSERT INTO child VALUES (1, 10)"
            }
        )
        async with database.transaction() as transaction:
            await transaction.execute(
                mariadb.update(Parent)
                .set(Parent.second.to(11))
                .where(Parent.first.eq(1))
            )
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(
                mariadb.select(Child.first, Child.second)
            )

    assert_eq(rows, [(1, 11)])


@test(mark="slow")
async def composite_second_member_index_is_not_hidden_as_support() -> None:
    """An index on only the second member cannot support the composite FK."""
    server = await load_fixture(provide_mariadb_server())

    class Parent[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Parent[mariadb.Row]]]
        first: mariadb.Col[int] = mariadb.Integer(primary_key=True)
        second: mariadb.Col[int] = mariadb.Integer(primary_key=True)

    class Child[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Child[mariadb.Row]]]
        first: mariadb.Col[int] = mariadb.Integer()
        second: mariadb.Col[int] = mariadb.Integer()
        __foreign_keys__: ClassVar = [
            mariadb.ForeignKeyConstraint(
                first, second, references=(Parent.first, Parent.second)
            )
        ]

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": mariadb.scaffold([Parent, Child])
                + "CREATE INDEX unexpected ON child(second)"
            }
        )
        report = await database.verify([Child], policy="warn")

    assert_eq(
        [
            (fact.object_name, fact.status)
            for fact in report.facts
            if fact.kind == "index.presence"
        ],
        [("unexpected", "drift")],
    )


@test(
    [
        Param(value=attribute, name=attribute)
        for attribute in ("length", "collation", "precision", "scale")
    ],
    mark="fast",
)
def native_storage_parameters_must_match(attribute: str) -> None:
    """Explicit local storage is checked rather than copied from the target."""

    class Parent[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Parent[mariadb.Row]]]
        text: mariadb.Col[str] = mariadb.Text(
            length=80, collation="utf8mb4_unicode_ci", unique=True
        )
        number: mariadb.Col[Decimal] = mariadb.Decimal(
            precision=10, scale=2, unique=True
        )

    with assert_raises(mariadb.ModelDeclarationError):

        class Child[S = mariadb.Pending](mariadb.Model[S]):
            __row_type__: ClassVar[mariadb.ReadType[Child[mariadb.Row]]]
            text: mariadb.Col[str] = mariadb.Text(
                length=81 if attribute == "length" else 80,
                collation="utf8mb4_bin"
                if attribute == "collation"
                else "utf8mb4_unicode_ci",
            )
            number: mariadb.Col[Decimal] = mariadb.Decimal(
                precision=11 if attribute == "precision" else 10,
                scale=3 if attribute == "scale" else 2,
            )
            __foreign_keys__: ClassVar = [
                mariadb.ForeignKeyConstraint(text, references=(Parent.text,)),
                mariadb.ForeignKeyConstraint(number, references=(Parent.number,)),
            ]


@test(mark="fast")
def declarations_snapshot_the_constraint_list() -> None:
    """Mutating the class-body list cannot change the model's fixed contract."""

    class Parent[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Parent[sqlite.Row]]]
        id: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    class Child[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Child[sqlite.Row]]]
        parent_id: sqlite.Col[int] = sqlite.Integer()
        __foreign_keys__: ClassVar = [
            sqlite.ForeignKeyConstraint(parent_id, references=(Parent.id,))
        ]

    before = sqlite.scaffold([Child])
    Child.__foreign_keys__.clear()

    assert_eq(sqlite.scaffold([Child]), before)


@test(mark="fast")
def constraint_values_are_frozen() -> None:
    """A declaration cannot change its action after binding."""
    constraint = sqlite.ForeignKeyConstraint(
        sqlite.Integer(), references=(sqlite.Integer(),)
    )

    with assert_raises(FrozenInstanceError):
        constraint.on_delete = "CASCADE"  # ty: ignore[invalid-assignment]


@test(
    [
        Param(value=change, name=change)
        for change in ("pair-order", "mapping", "action", "duplicate", "missing")
    ],
    mark="medium",
)
async def sqlite_grouped_catalog_drift(change: str) -> None:
    """Ordered pairs, referential actions, and multiplicity participate in drift."""

    class Parent[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Parent[sqlite.Row]]]
        first: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        second: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    class Child[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Child[sqlite.Row]]]
        first: sqlite.Col[int] = sqlite.Integer()
        second: sqlite.Col[int] = sqlite.Integer()
        __foreign_keys__: ClassVar = [
            sqlite.ForeignKeyConstraint(
                first, second, references=(Parent.first, Parent.second)
            )
        ]

    relationship = ", FOREIGN KEY(first, second) REFERENCES parent(first, second)"
    constraints = {
        "pair-order": ", FOREIGN KEY(second, first) REFERENCES parent(second, first)",
        "mapping": ", FOREIGN KEY(first, second) REFERENCES parent(second, first)",
        "action": relationship + " ON DELETE CASCADE",
        "duplicate": relationship + relationship,
        "missing": "",
    }
    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": f"CREATE TABLE parent (first INTEGER NOT NULL, second INTEGER NOT NULL, PRIMARY KEY(first, second), UNIQUE(second, first)) STRICT; CREATE TABLE child (first INTEGER NOT NULL, second INTEGER NOT NULL{constraints[change]}) STRICT"
            }
        )
        with assert_raises(sqlite.SchemaVerificationError) as error:
            await database.verify([Child])

    assert_eq(
        [
            fact.status
            for fact in error.exception.result.facts
            if fact.kind == "foreign_keys.grouping"
        ],
        ["drift"],
    )


@test(mark="medium")
async def sqlite_overlapping_constraints_remain_distinct() -> None:
    """A scalar relationship can coexist with repeated composite relationships."""

    class Parent[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Parent[sqlite.Row]]]
        first: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        second: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        __indexes__: ClassVar = [sqlite.Index(first, unique=True)]

    class Child[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Child[sqlite.Row]]]
        first: sqlite.FKCol[Parent, int] = sqlite.ForeignKey(Parent.first)
        second: sqlite.Col[int] = sqlite.Integer()
        __foreign_keys__: ClassVar = [
            sqlite.ForeignKeyConstraint(
                first, second, references=(Parent.first, Parent.second)
            ),
            sqlite.ForeignKeyConstraint(
                first, second, references=(Parent.first, Parent.second)
            ),
        ]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate({"001": sqlite.scaffold([Parent, Child])})
        report = await database.verify([Parent, Child])

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "foreign_keys.grouping"],
        ["matched", "matched"],
    )


@test(
    [
        Param(value=change, name=change)
        for change in ("pair-order", "mapping", "action", "duplicate", "missing")
    ],
    mark="slow",
)
async def mariadb_grouped_catalog_drift(change: str) -> None:
    """Ordered pairs, referential actions, and multiplicity participate in drift."""
    server = await load_fixture(provide_mariadb_server())

    class Parent[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Parent[mariadb.Row]]]
        first: mariadb.Col[int] = mariadb.Integer(primary_key=True)
        second: mariadb.Col[int] = mariadb.Integer(primary_key=True)

    class Child[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Child[mariadb.Row]]]
        first: mariadb.Col[int] = mariadb.Integer()
        second: mariadb.Col[int] = mariadb.Integer()
        __foreign_keys__: ClassVar = [
            mariadb.ForeignKeyConstraint(
                first, second, references=(Parent.first, Parent.second)
            )
        ]

    relationship = ", FOREIGN KEY(first, second) REFERENCES parent(first, second)"
    constraints = {
        "pair-order": ", FOREIGN KEY(second, first) REFERENCES parent(second, first)",
        "mapping": ", FOREIGN KEY(first, second) REFERENCES parent(second, first)",
        "action": relationship + " ON DELETE CASCADE",
        "duplicate": relationship + relationship,
        "missing": "",
    }
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": f"CREATE TABLE parent (first BIGINT NOT NULL, second BIGINT NOT NULL, PRIMARY KEY(first, second), UNIQUE(second, first)) ENGINE=InnoDB; CREATE TABLE child (first BIGINT NOT NULL, second BIGINT NOT NULL{constraints[change]}) ENGINE=InnoDB"
            }
        )
        with assert_raises(mariadb.SchemaVerificationError) as error:
            await database.verify([Child])

    assert_eq(
        [
            fact.status
            for fact in error.exception.result.facts
            if fact.kind == "foreign_keys.grouping"
        ],
        ["drift"],
    )


@test(mark="slow")
async def mariadb_overlapping_constraints_remain_distinct() -> None:
    """A scalar relationship can coexist with repeated composite relationships."""
    server = await load_fixture(provide_mariadb_server())

    class Parent[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Parent[mariadb.Row]]]
        first: mariadb.Col[int] = mariadb.Integer(primary_key=True)
        second: mariadb.Col[int] = mariadb.Integer(primary_key=True)
        __indexes__: ClassVar = [mariadb.Index(first, unique=True)]

    class Child[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Child[mariadb.Row]]]
        first: mariadb.FKCol[Parent, int] = mariadb.ForeignKey(Parent.first)
        second: mariadb.Col[int] = mariadb.Integer()
        __foreign_keys__: ClassVar = [
            mariadb.ForeignKeyConstraint(
                first, second, references=(Parent.first, Parent.second)
            ),
            mariadb.ForeignKeyConstraint(
                first, second, references=(Parent.first, Parent.second)
            ),
        ]

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([Parent, Child])})
        report = await database.verify([Parent, Child])

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "foreign_keys.grouping"],
        ["matched", "matched"],
    )


@test(mark="medium")
async def sqlite_self_references_bind_after_column_ownership() -> None:
    """A local descriptor tuple can target the declaring table's composite key."""

    class Node[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Node[sqlite.Row]]]
        tenant_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        node_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        parent_tenant: sqlite.Col[int | None] = sqlite.Integer(nullable=True)
        parent_id: sqlite.Col[int | None] = sqlite.Integer(nullable=True)
        __foreign_keys__: ClassVar = [
            sqlite.ForeignKeyConstraint(
                parent_tenant, parent_id, references=(tenant_id, node_id)
            )
        ]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate({"001": sqlite.scaffold([Node])})
        report = await database.verify([Node])

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "foreign_keys.grouping"],
        ["matched"],
    )


@test(mark="slow")
async def mariadb_self_references_bind_after_column_ownership() -> None:
    """A local descriptor tuple can target the declaring table's composite key."""
    server = await load_fixture(provide_mariadb_server())

    class Node[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Node[mariadb.Row]]]
        tenant_id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
        node_id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
        parent_tenant: mariadb.Col[int | None] = mariadb.Integer(nullable=True)
        parent_id: mariadb.Col[int | None] = mariadb.Integer(nullable=True)
        __foreign_keys__: ClassVar = [
            mariadb.ForeignKeyConstraint(
                parent_tenant, parent_id, references=(tenant_id, node_id)
            )
        ]

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([Node])})
        report = await database.verify([Node])

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "foreign_keys.grouping"],
        ["matched"],
    )
