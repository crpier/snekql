"""Query sources distinguish declarations, values, and native query roles."""

from typing import Any, ClassVar

from snektest import Param, assert_eq, assert_raises, test

from snekql import mariadb, sqlite


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [
        Param(verb, name=verb)
        for verb in ("select", "join", "left_join", "update", "delete", "alias")
    ],
    [
        Param(kind, name=kind)
        for kind in (
            "pending-instance",
            "row-instance",
            "pending-specialization",
            "row-specialization",
            "any-specialization",
            "row-witness",
            "lookalike",
        )
    ],
    mark="fast",
)
def builders_reject_non_declaration_sources(backend: str, verb: str, kind: str) -> None:
    """Values, annotations and structural pretenders cannot replace declarations."""

    class Account[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    class MariaAccount[State = mariadb.Pending](mariadb.Model[State]):
        __row_type__: ClassVar[mariadb.ReadType[MariaAccount[mariadb.Row]]]
        account_id: mariadb.Col[int] = mariadb.Integer(primary_key=True)

    class Lookalike:
        """An unrelated class cannot supply a query source."""

    namespace: Any = sqlite if backend == "sqlite" else mariadb
    model: Any = Account if backend == "sqlite" else MariaAccount
    sources: dict[str, Any] = {
        "pending-instance": model(account_id=1),
        "row-instance": namespace.complete(model, account_id=1),
        "pending-specialization": model[namespace.Pending],
        "row-specialization": model[namespace.Row],
        "any-specialization": model[Any],
        "row-witness": model.__row_type__,
        "lookalike": Lookalike,
    }

    with assert_raises(namespace.QueryConstructionError):
        if verb in {"join", "left_join"}:
            getattr(namespace.select(model), verb)(
                sources[kind], on=model.account_id.eq_col(model.account_id)
            )
        elif verb == "alias":
            namespace.alias(sources[kind], object, name="invalid")
        else:
            getattr(namespace, verb)(sources[kind])


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [Param(verb, name=verb) for verb in ("update", "delete")],
    mark="fast",
)
def wrong_backend_does_not_bind_mutation_target(backend: str, verb: str) -> None:
    """A rejected backend must not evaluate the other model's deferred targets."""
    calls: list[str] = []

    class Account[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        parent_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            lambda: (calls.append("target"), Account.account_id)[1], default=None
        )

    class MariaAccount[State = mariadb.Pending](mariadb.Model[State]):
        __row_type__: ClassVar[mariadb.ReadType[MariaAccount[mariadb.Row]]]
        account_id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
        parent_id: mariadb.FKCol[MariaAccount, int | None] = mariadb.ForeignKey(
            lambda: (calls.append("target"), MariaAccount.account_id)[1], default=None
        )

    namespace: Any = sqlite if backend == "sqlite" else mariadb
    foreign: Any = MariaAccount if backend == "sqlite" else Account

    with assert_raises(namespace.QueryConstructionError):
        getattr(namespace, verb)(foreign)

    assert_eq(calls, [])
