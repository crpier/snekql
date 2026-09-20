"""Typed table roles through the public Query Builder."""

from typing import TYPE_CHECKING, assert_type

from snektest import Param, assert_eq, assert_raises, test

from snekql import mariadb, sqlite
from tests.query.test_join_compilation import Order, User


class ManagerRole:
    """A second User role in one query."""


@test(mark="fast")
def self_join_qualifies_roles_independently() -> None:
    """One physical table can occupy two independently referenced roles."""
    manager = sqlite.alias(User, ManagerRole, name="manager")
    compiled = (
        sqlite.select(User.email, manager.column(User.email))
        .join(manager, on=User.id.eq_col(manager.column(User.id)))
        .all()
        .compile()
    )

    assert_eq(
        compiled.sql,
        'SELECT "user"."email", "manager"."email" FROM "user" '
        'INNER JOIN "user" AS "manager" ON "user"."id" = "manager"."id"',
    )


class ReviewerRole:
    """A distinct User role, not interchangeable with ManagerRole."""


@test(
    [
        Param("user", name="base-name"),
        Param("manager", name="same-name"),
        Param("MANAGER", name="case-collision"),
    ],
    mark="fast",
)
def colliding_alias_names_are_rejected(name: str) -> None:
    """SQL names must identify only one visible source, regardless of role type."""
    manager = sqlite.alias(User, ManagerRole, name="manager")
    reviewer = sqlite.alias(User, ReviewerRole, name=name)
    query = (
        sqlite.select(User)
        .join(manager, on=User.id.eq_col(manager.column(User.id)))
        .join(reviewer, on=User.id.eq_col(reviewer.column(User.id)))
        .all()
    )

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


@test(mark="fast")
def one_role_cannot_name_two_visible_aliases() -> None:
    """Distinct SQL names do not make the same static role distinguishable."""
    manager = sqlite.alias(User, ManagerRole, name="manager")
    duplicate = sqlite.alias(User, ManagerRole, name="other_manager")
    query = (
        sqlite.select(manager)
        .join(duplicate, on=manager.column(User.id).eq_col(duplicate.column(User.id)))
        .all()
    )

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


@test(mark="fast")
def unjoined_alias_on_the_right_is_rejected() -> None:
    """An alias cannot borrow the scope membership of its original table."""
    manager = sqlite.alias(User, ManagerRole, name="manager")
    query = sqlite.select(User).where(User.id.eq_col(manager.column(User.id)))

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


@test(mark="fast")
def nested_alias_cannot_shadow_an_outer_name() -> None:
    """Distinct Python roles cannot silently resolve to one SQL qualifier."""
    manager = sqlite.alias(User, ManagerRole, name="person")
    reviewer = sqlite.alias(User, ReviewerRole, name="person")
    query = sqlite.select(manager).where(
        sqlite.exists(
            sqlite.select(reviewer.column(User.id)).where(
                reviewer.column(User.id).eq_col(manager.column(User.id))
            )
        )
    )

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


@test(mark="fast")
def alias_does_not_rebind_the_original_column() -> None:
    """Creating a role leaves ordinary query compilation and descriptor identity alone."""
    original = User.email
    before = sqlite.select(User.email).all().compile()
    manager = sqlite.alias(User, ManagerRole, name="manager")
    sqlite.select(manager.column(User.email)).all().compile()

    assert_eq(sqlite.select(User.email).all().compile(), before)
    assert_eq(User.email is original, True)


@test(
    [
        Param("", name="empty"),
        Param("bad name", name="space"),
        Param('x"; DROP TABLE user', name="sql"),
    ],
    mark="fast",
)
def alias_rejects_invalid_sql_names(name: str) -> None:
    """Alias names are identifiers, never interpolated SQL fragments."""
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.alias(User, ManagerRole, name=name)


@test(mark="fast")
def alias_rejects_another_models_column() -> None:
    """Column ownership survives dynamic calls as well as static annotations."""
    manager = sqlite.alias(User, ManagerRole, name="manager")

    with assert_raises(sqlite.QueryConstructionError):
        manager.column(Order.id)  # ty: ignore[invalid-argument-type]


@test(mark="fast")
def alias_is_not_a_write_target() -> None:
    """Query-only aliases cannot be passed to mutation verbs."""
    manager = sqlite.alias(User, ManagerRole, name="manager")

    with assert_raises(sqlite.QueryConstructionError):
        sqlite.delete(manager)  # ty: ignore[invalid-argument-type]


if TYPE_CHECKING:

    async def check_role_types(transaction: sqlite.Transaction) -> None:
        """Role identity remains nominal through joins, projections, and helpers."""
        manager = sqlite.alias(User, ManagerRole, name="manager")
        reviewer = sqlite.alias(User, ReviewerRole, name="reviewer")
        query = sqlite.select(manager).all()
        assert_type(await transaction.fetch_all(query), list[User[sqlite.Fetched]])
        assert_type(
            await transaction.fetch_all(
                sqlite.select(manager.column(User.email)).all()
            ),
            list[str],
        )
        query.where(reviewer.column(User.email).eq("x"))  # ty: ignore[invalid-argument-type]
        query.where(User.email.eq("x"))  # ty: ignore[invalid-argument-type]
        manager.column(Order.id)  # ty: ignore[invalid-argument-type]
        sqlite.update(User).set(manager.column(User.email).to("changed"))  # ty: ignore[no-matching-overload]
        sqlite.update(manager)  # ty: ignore[invalid-argument-type]
        sqlite.scaffold([manager])  # ty: ignore[invalid-argument-type]
        mariadb.select(manager)  # ty: ignore[no-matching-overload]
        mariadb.select(manager.column(User.id))  # ty: ignore[no-matching-overload]


@test(mark="fast")
def alias_assignment_cannot_target_the_physical_model() -> None:
    """Dynamic assignment calls cannot turn a query role into a write target."""
    manager = sqlite.alias(User, ManagerRole, name="manager")

    with assert_raises(sqlite.QueryConstructionError):
        sqlite.update(User).set(manager.column(User.email).to("changed"))  # ty: ignore[no-matching-overload]


@test(mark="fast")
def alias_rejects_mixed_backend_models() -> None:
    """Erased callers cannot ask MariaDB to alias a SQLite model."""
    with assert_raises(mariadb.QueryConstructionError):
        mariadb.alias(User, ManagerRole, name="manager")  # ty: ignore[no-matching-overload]


@test(mark="fast")
def alias_requires_a_declared_table() -> None:
    """A backend's model base is not a physical table source."""
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.alias(sqlite.Model, ManagerRole, name="manager")
