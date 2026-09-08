"""Scalar foreign-key targets need independent uniqueness, not tuple membership."""

from __future__ import annotations

from typing import Any, ClassVar

from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite
from snekql.errors import ExecutionError, SchemaError


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

    class Parent[S = sqlite.Pending](sqlite.Model[S, "Parent[sqlite.Fetched]"]):
        """Uniqueness belongs to the pair."""

        a: Parent.Col[int] = sqlite.Integer(primary_key=True)
        b: Parent.Col[int] = sqlite.Integer(primary_key=True)
        __indexes__: ClassVar[list[sqlite.Index[Any]]] = (
            [sqlite.Index(a, b, unique=True)]
            if case[1] == "composite_unique"
            else [sqlite.Index(a)]
            if case[1] == "nonunique"
            else []
        )

    class Child[S = sqlite.Pending](sqlite.Model[S, "Child[sqlite.Fetched]"]):
        """An invalid scalar reference to one member of the pair."""

        parent: Child.FKCol[Parent, int] = sqlite.ForeignKey(
            Parent.a if case[0] == "a" else Parent.b
        )

    with assert_raises(SchemaError):
        sqlite.scaffold([Parent, Child])


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

    class Parent[S = sqlite.Pending](sqlite.Model[S, "Parent[sqlite.Fetched]"]):
        """A target with a genuinely independent key for the selected column."""

        a: Parent.Col[int] = sqlite.Integer(
            primary_key=kind not in {"nonpk_index", "column_unique"},
            unique=kind == "column_unique",
            nullable=False,
        )
        b: Parent.Col[int] = sqlite.Integer(
            primary_key=kind != "single_pk", nullable=False
        )
        __indexes__: ClassVar[list[sqlite.Index[Any]]] = (
            [sqlite.Index(b, unique=True)]
            if kind == "index_b"
            else [sqlite.Index(a, unique=True)]
            if kind in {"index_a", "nonpk_index"}
            else []
        )

    class Child[S = sqlite.Pending](sqlite.Model[S, "Child[sqlite.Fetched]"]):
        """One scalar foreign key, not a composite-FK declaration."""

        parent: Child.FKCol[Parent, int] = sqlite.ForeignKey(
            Parent.b if kind == "index_b" else Parent.a,
        )

    # These generated fixtures contain no semicolons in identifiers or literals.
    ddl = sqlite.scaffold([Parent, Child])
    migrations = {
        str(index): statement
        for index, statement in enumerate(ddl.split(";"))
        if statement.strip()
    }
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate(migrations)
        await database.verify([Parent, Child])
        async with database.transaction() as setup:
            await setup.execute(sqlite.insert(Parent(a=10, b=20)))

        expected = 20 if kind == "index_b" else 10
        async with database.transaction() as tx:
            await tx.execute(sqlite.insert(Child(parent=expected)))

        async with database.transaction() as tx:
            rows = await tx.fetch_all(sqlite.select(Child.parent).all())

        with assert_raises(ExecutionError) as caught:
            async with database.transaction() as tx:
                await tx.execute(sqlite.insert(Child(parent=999)))
        assert_eq(type(caught.exception.__cause__).__name__, "IntegrityError")

    assert_eq(rows, [expected])
