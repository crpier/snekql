"""Scaffold pure-function tests: model -> initial CREATE TABLE DDL text."""

from __future__ import annotations

from typing import Any, ClassVar

from snektest import assert_eq, assert_true, test

from snekql.mariadb import scaffold as scaffold_mariadb
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


class ScaffoldTeam[S = Pending](Model[S, "ScaffoldTeam[Fetched]"]):
    """Referenced table anchoring the join table's foreign keys."""

    id: ScaffoldTeam.GenCol[int] = Integer(primary_key=True, auto_increment=True)


class ScaffoldMember[S = Pending](Model[S, "ScaffoldMember[Fetched]"]):
    """Join table whose identity is a (team, user) column pair."""

    team_id: ScaffoldMember.FKCol[ScaffoldTeam, int] = ForeignKey(
        ScaffoldTeam.id, primary_key=True
    )
    user_id: ScaffoldMember.FKCol[ScaffoldUser, int] = ForeignKey(
        ScaffoldUser.id, primary_key=True
    )
    role: ScaffoldMember.Col[str] = Text(nullable=False)


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


class ScaffoldDefaultNull[S = Pending](Model[S, "ScaffoldDefaultNull[Fetched]"]):
    """Model whose column omits ``nullable=`` to exercise the NOT NULL default."""

    id: ScaffoldDefaultNull.GenCol[int] = Integer(primary_key=True, auto_increment=True)
    name: ScaffoldDefaultNull.Col[str] = Text()


@test(mark="fast")
def scaffold_defaults_unset_nullable_to_not_null() -> None:
    """A column declared without ``nullable=`` scaffolds as NOT NULL (#203 F9).

    The non-optional ``Col[str]`` read type promises a non-``None`` value, so the
    physical column must reject NULL rather than silently admitting one.
    """

    ddl = scaffold([ScaffoldDefaultNull])

    assert_true('"name" TEXT NOT NULL' in ddl)


@test(mark="fast")
def scaffold_emits_foreign_key_constraint() -> None:
    """Scaffold renders a table-level FOREIGN KEY ... REFERENCES constraint."""

    ddl = scaffold([ScaffoldPost])

    assert_true("FOREIGN KEY" in ddl)
    assert_true('REFERENCES "scaffold_user" ("id")' in ddl)


class ScaffoldComment[S = Pending](Model[S, "ScaffoldComment[Fetched]"]):
    """Owned model whose author reference declares referential actions."""

    id: ScaffoldComment.GenCol[int] = Integer(primary_key=True, auto_increment=True)
    author_id: ScaffoldComment.FKCol[ScaffoldUser, int] = ForeignKey(
        ScaffoldUser.id, nullable=False, on_delete="CASCADE", on_update="RESTRICT"
    )


@test(mark="fast")
def scaffold_emits_referential_actions() -> None:
    """Declared `on_delete`/`on_update` render ON DELETE / ON UPDATE clauses."""

    ddl = scaffold([ScaffoldComment])

    assert_true(
        'REFERENCES "scaffold_user" ("id") ON DELETE CASCADE ON UPDATE RESTRICT' in ddl
    )


@test(mark="fast")
def mariadb_scaffold_emits_referential_actions() -> None:
    """MariaDB renders the same referential-action clauses via the shared compiler."""

    ddl = scaffold_mariadb([ScaffoldComment])

    assert_true(
        "REFERENCES `scaffold_user` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT" in ddl
    )


@test(mark="fast")
def scaffold_emits_table_level_composite_primary_key() -> None:
    """Two PK columns render one table-level PRIMARY KEY, no inline PK clauses."""

    ddl = scaffold([ScaffoldMember])

    expected = (
        'CREATE TABLE "scaffold_member" ('
        '"team_id" INTEGER NOT NULL, "user_id" INTEGER NOT NULL, '
        '"role" TEXT NOT NULL, '
        'PRIMARY KEY ("team_id", "user_id"), '
        'FOREIGN KEY ("team_id") REFERENCES "scaffold_team" ("id"), '
        'FOREIGN KEY ("user_id") REFERENCES "scaffold_user" ("id")) STRICT;'
    )
    assert_eq(ddl, expected)


@test(mark="fast")
def scaffold_of_no_models_is_empty() -> None:
    """Scaffolding an empty model list yields empty text."""

    assert_eq(scaffold([]), "")
