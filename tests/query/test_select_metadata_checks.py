"""Namespace checks stay current when SELECT reuses validated anchor metadata."""

from typing import Any, ClassVar

from snektest import Param, assert_eq, assert_raises, test

from snekql import mariadb, sqlite


class Local[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Local[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    label: sqlite.Col[str] = sqlite.Text()


class Remote[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[Remote[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    label: mariadb.Col[str] = mariadb.Text()


@test([Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")], mark="fast")
def previously_valid_anchor_does_not_admit_foreign_projection(backend: str) -> None:
    namespace: Any = sqlite if backend == "sqlite" else mariadb
    own: Any = Local if backend == "sqlite" else Remote
    foreign: Any = Remote if backend == "sqlite" else Local
    assert_eq(namespace.select(own.id, own.label).compile().params, ())
    with assert_raises(namespace.QueryConstructionError):
        namespace.select(own.id, foreign.label)
    with assert_raises(namespace.QueryConstructionError):
        namespace.select(
            own.id,
            namespace.scalar(
                (mariadb if backend == "sqlite" else sqlite).select(foreign.id)
            ),
        )
    assert_eq(namespace.select(own).compile().params, ())
    with assert_raises(namespace.QueryConstructionError):
        namespace.select(foreign)


@test(mark="fast")
def same_backend_other_sources_are_available_for_later_joins() -> None:
    class Peer[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Peer[sqlite.Row]]]
        id: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    projection = sqlite.select(Local.id, Peer.id)
    with assert_raises(sqlite.QueryCompilationError):
        projection.compile()
    joined = projection.join(Peer, on=Local.id.eq_col(Peer.id))
    assert_eq(
        joined.compile().sql,
        'SELECT "local"."id", "peer"."id" FROM "local" '
        'INNER JOIN "peer" ON "local"."id" = "peer"."id"',
    )


@test(mark="fast")
def alias_projection_keeps_relation_identity() -> None:
    class Role:
        pass

    alias = sqlite.alias(Local, Role, name="entry")
    own = alias.column(Local.id)
    assert_eq(sqlite.select(own).compile().sql, 'SELECT "id" FROM "local" AS "entry"')
    projected = sqlite.select(own, Local.id)
    with assert_raises(sqlite.QueryCompilationError):
        projected.compile()
    joined = projected.join(Local, on=own.eq_col(Local.id))
    assert_eq(
        joined.compile().sql,
        'SELECT "entry"."id", "local"."id" FROM "local" AS "entry" '
        'INNER JOIN "local" ON "entry"."id" = "local"."id"',
    )


@test([Param("model", name="model"), Param("column", name="column")], mark="fast")
def deferred_binding_remains_required_before_select(shape: str) -> None:
    class Node[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Node[sqlite.Row]]]
        id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        parent: sqlite.FKCol[Node, int | None] = sqlite.ForeignKey(
            lambda: Node.id, default=None
        )

    class Broken[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Broken[sqlite.Row]]]
        id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        parent: sqlite.FKCol[Local, int | None] = sqlite.ForeignKey(  # ty: ignore[invalid-assignment]
            lambda: Remote.id,
            default=None,
        )

    for _ in range(2):
        if shape == "model":
            assert_eq(
                sqlite.select(Node).compile().sql, 'SELECT "id", "parent" FROM "node"'
            )
            with assert_raises(sqlite.QueryConstructionError):
                sqlite.select(Broken)
        else:
            assert_eq(sqlite.select(Node.id).compile().sql, 'SELECT "id" FROM "node"')
            with assert_raises(sqlite.QueryConstructionError):
                sqlite.select(Broken.id)
