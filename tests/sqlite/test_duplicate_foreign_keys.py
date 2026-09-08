"""Schema verification preserves all constraints sharing one local column."""

from __future__ import annotations

from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite
from snekql.errors import SchemaVerificationError


class Parent[S = sqlite.Pending](sqlite.Model[S, "Parent[sqlite.Fetched]"]):
    """The declared target."""

    id: Parent.Col[int] = sqlite.Integer(primary_key=True)


class Child[S = sqlite.Pending](sqlite.Model[S, "Child[sqlite.Fetched]"]):
    """A model declares one scalar relationship."""

    parent_id: Child.FKCol[Parent, int] = sqlite.ForeignKey(Parent.id, primary_key=True)


@test(
    [
        Param(value=(kind, order), name=f"{kind}_{order}")
        for kind in ("target", "delete", "update", "duplicate")
        for order in ("forward", "reverse")
    ],
    mark="medium",
)
async def verification_reports_extra_foreign_key(case: tuple[str, str]) -> None:
    """Warn and strict policies see every extra constraint in either catalog order."""

    target, description = {
        "target": ("other(id)", "other.id"),
        "delete": ("parent(id) ON DELETE CASCADE", "parent.id ON DELETE CASCADE"),
        "update": ("parent(id) ON UPDATE CASCADE", "parent.id ON UPDATE CASCADE"),
        "duplicate": ("parent(id)", "parent.id"),
    }[case[0]]
    expected_name, extra_name = (
        ("a_expected", "z_extra") if case[1] == "forward" else ("z_expected", "a_extra")
    )
    constraints = [
        f"CONSTRAINT {expected_name} FOREIGN KEY (parent_id) REFERENCES parent(id)",
        f"CONSTRAINT {extra_name} FOREIGN KEY (parent_id) REFERENCES {target}",
    ]
    if case[1] == "reverse":
        constraints.reverse()
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate(
            {
                "parent": "CREATE TABLE parent (id INTEGER PRIMARY KEY) STRICT",
                "other": "CREATE TABLE other (id INTEGER PRIMARY KEY) STRICT",
                "child": "CREATE TABLE child (parent_id INTEGER PRIMARY KEY, "
                + ", ".join(constraints)
                + ") STRICT",
            }
        )
        result = await database.verify([Parent, Child], policy="warn")
        with assert_raises(SchemaVerificationError):
            await database.verify([Parent, Child], policy="strict")

    assert_eq(
        [issue.detail for issue in result.issues],
        [
            f"foreign key on column 'parent_id' -> {description} exists in the database but not in the model"
        ],
    )


@test(mark="medium")
async def renamed_single_constraint_is_not_drift() -> None:
    """Constraint names are cosmetic; one matching relationship stays clean."""

    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate(
            {
                "parent": "CREATE TABLE parent (id INTEGER PRIMARY KEY) STRICT",
                "child": "CREATE TABLE child (parent_id INTEGER PRIMARY KEY, CONSTRAINT custom_name FOREIGN KEY (parent_id) REFERENCES parent(id)) STRICT",
            }
        )
        result = await database.verify([Parent, Child])

    assert_eq(result.issues, ())


@test(mark="medium")
async def single_changed_constraint_keeps_existing_diagnostic() -> None:
    """An ordinary action mismatch still reports expected and found facts."""

    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate(
            {
                "parent": "CREATE TABLE parent (id INTEGER PRIMARY KEY) STRICT",
                "child": "CREATE TABLE child (parent_id INTEGER PRIMARY KEY, FOREIGN KEY (parent_id) REFERENCES parent(id) ON DELETE CASCADE) STRICT",
            }
        )
        result = await database.verify([Parent, Child], policy="warn")

    assert_eq(
        [issue.detail for issue in result.issues],
        [
            "foreign key on column 'parent_id' differs: expected -> parent.id ON DELETE NO ACTION ON UPDATE NO ACTION, found -> parent.id ON DELETE CASCADE ON UPDATE NO ACTION"
        ],
    )
