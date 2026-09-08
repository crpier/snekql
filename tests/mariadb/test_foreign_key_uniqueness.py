"""Scalar foreign-key targets need independent uniqueness, not tuple membership."""

from __future__ import annotations

from typing import Any, ClassVar

from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb
from snekql.errors import ExecutionError, SchemaError
from tests.helpers import provide_mariadb_server


@test(
    [
        Param(value=(member, index), name=f"{member}_{index}")
        for member in ("a", "b")
        for index in ("none", "nonunique", "composite_unique")
    ],
    mark="fast",
)
def scaffold_rejects_composite_primary_key_component(case: tuple[str, str]) -> None:
    """A two-column primary key does not make either column independently unique."""

    class Parent[S = mariadb.Pending](mariadb.Model[S, "Parent[mariadb.Fetched]"]):
        """Uniqueness belongs to the pair."""

        a: Parent.Col[int] = mariadb.Integer(primary_key=True)
        b: Parent.Col[int] = mariadb.Integer(primary_key=True)
        __indexes__: ClassVar[list[mariadb.Index[Any]]] = (
            [mariadb.Index(a, b, unique=True)]
            if case[1] == "composite_unique"
            else [mariadb.Index(a)]
            if case[1] == "nonunique"
            else []
        )

    class Child[S = mariadb.Pending](mariadb.Model[S, "Child[mariadb.Fetched]"]):
        """An invalid scalar reference to one member of the pair."""

        parent: Child.FKCol[Parent, int] = mariadb.ForeignKey(
            Parent.a if case[0] == "a" else Parent.b
        )

    with assert_raises(SchemaError):
        mariadb.scaffold([Parent, Child])


@test(
    [
        Param(value=kind, name=kind)
        for kind in ("single_pk", "column_unique", "index_a", "index_b", "nonpk_index")
    ],
    mark="medium",
)
async def accepted_scalar_targets_support_scaffold_replay_and_inserts(
    kind: str,
) -> None:
    """Every accepted uniqueness form produces an enforceable scalar relationship."""

    server = await load_fixture(provide_mariadb_server())

    class Parent[S = mariadb.Pending](mariadb.Model[S, "Parent[mariadb.Fetched]"]):
        """A target with a genuinely independent key for the selected column."""

        a: Parent.Col[int] = mariadb.Integer(
            primary_key=kind not in {"nonpk_index", "column_unique"},
            unique=kind == "column_unique",
            nullable=False,
        )
        b: Parent.Col[int] = mariadb.Integer(
            primary_key=kind != "single_pk", nullable=False
        )
        __indexes__: ClassVar[list[mariadb.Index[Any]]] = (
            [mariadb.Index(b, unique=True)]
            if kind == "index_b"
            else [mariadb.Index(a, unique=True)]
            if kind in {"index_a", "nonpk_index"}
            else []
        )

    class Child[S = mariadb.Pending](mariadb.Model[S, "Child[mariadb.Fetched]"]):
        """One scalar foreign key, not a composite-FK declaration."""

        parent: Child.FKCol[Parent, int] = mariadb.ForeignKey(
            Parent.b if kind == "index_b" else Parent.a,
        )

    # These generated fixtures contain no semicolons in identifiers or literals.
    ddl = mariadb.scaffold([Parent, Child])
    migrations = {
        str(index): statement
        for index, statement in enumerate(ddl.split(";"))
        if statement.strip()
    }
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(migrations)
        await database.verify([Parent, Child])
        async with database.transaction() as setup:
            await setup.execute(mariadb.insert(Parent(a=10, b=20)))

        expected = 20 if kind == "index_b" else 10
        async with database.transaction() as tx:
            await tx.execute(mariadb.insert(Child(parent=expected)))

        async with database.transaction() as tx:
            rows = await tx.fetch_all(mariadb.select(Child.parent).all())

        with assert_raises(ExecutionError) as caught:
            async with database.transaction() as tx:
                await tx.execute(mariadb.insert(Child(parent=999)))
        assert_eq(type(caught.exception.__cause__).__name__, "IntegrityError")

    assert_eq(rows, [expected])
