"""Scaffold pure-function tests: model -> initial CREATE TABLE DDL text."""

from __future__ import annotations

from typing import Any, ClassVar

from snektest import assert_eq, assert_true, test

from snekql.sqlite import (
    Fetched,
    ForeignKey,
    Index,
    Integer,
    Model,
    Pending,
    Text,
    scaffold,
)


class ScaffoldUser[S = Pending](Model[S, "ScaffoldUser[Fetched]"]):
    """Model with an index used to assert scaffolded DDL text."""

    id: ScaffoldUser.GenCol[int] = Integer(primary_key=True, auto_increment=True)
    email: ScaffoldUser.Col[str] = Text(nullable=False)
    __indexes__: ClassVar[list[Index[Any]]] = [
        Index(email, name="ix_scaffold_user_email"),
    ]


class ScaffoldPost[S = Pending](Model[S, "ScaffoldPost[Fetched]"]):
    """Model with a foreign key used to assert scaffolded FK DDL."""

    id: ScaffoldPost.GenCol[int] = Integer(primary_key=True, auto_increment=True)
    author_id: ScaffoldPost.FKCol[ScaffoldUser, int] = ForeignKey(ScaffoldUser.id)


_EXPECTED_USER_DDL = (
    'CREATE TABLE "scaffold_user" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, '
    '"email" TEXT NOT NULL) STRICT;\n'
    'CREATE INDEX "ix_scaffold_user_email" ON "scaffold_user" ("email");'
)


@test(mark="fast")
def scaffold_emits_create_table_and_index_ddl() -> None:
    """Scaffold renders the table create then a separate index create statement."""

    ddl = scaffold([ScaffoldUser])

    assert_eq(ddl, _EXPECTED_USER_DDL)


@test(mark="fast")
def scaffold_emits_foreign_key_constraint() -> None:
    """Scaffold renders a table-level FOREIGN KEY ... REFERENCES constraint."""

    ddl = scaffold([ScaffoldPost])

    assert_true("FOREIGN KEY" in ddl)
    assert_true('REFERENCES "scaffold_user" ("id")' in ddl)


@test(mark="fast")
def scaffold_of_no_models_is_empty() -> None:
    """Scaffolding an empty model list yields empty text."""

    assert_eq(scaffold([]), "")
