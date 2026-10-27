"""Insert conflict query construction and compilation tests."""

from __future__ import annotations

from typing import ClassVar

from snektest import assert_eq, assert_raises, test

from snekql import mariadb
from snekql.sqlite import (
    PENDING_GENERATION,
    DoNothing,
    DoUpdate,
    Integer,
    Model,
    Pending,
    QueryCompilationError,
    QueryConstructionError,
    ReadType,
    Row,
    Text,
    insert,
    insert_many,
    update,
)


@test(mark="fast")
def sqlite_conflict_update_compiles_multiple_inserted_values() -> None:
    """SQLite updates each named column from the attempted insert."""

    class User[S = Pending](Model[S]):
        """Table model with one conflict target and two mutable columns."""

        __row_type__: ClassVar[ReadType[User[Row]]]

        email: User.Col[str] = Text(nullable=False, unique=True)
        name: User.Col[str] = Text(nullable=False)
        status: User.Col[str] = Text(nullable=False)

    compiled = (
        insert(User(email="a@example.com", name="Alice", status="active")).on_conflict(
            User.email,
            action=DoUpdate(
                User.name.to_inserted(),
                User.status.to_inserted(),
            ),
        )
    ).compile()

    expected_sql = 'INSERT INTO "user" ("email", "name", "status") VALUES (?, ?, ?)'
    expected_sql += ' ON CONFLICT ("email") DO UPDATE SET'
    expected_sql += ' "name" = excluded."name", "status" = excluded."status"'
    assert_eq(compiled.sql, expected_sql)
    assert_eq(compiled.params, ("a@example.com", "Alice", "active"))

    assert_eq(compiled.backend, "sqlite")


@test(mark="fast")
def sqlite_conflict_do_nothing_compiles_without_assignments() -> None:
    """SQLite can discard an insert that conflicts with the named target."""

    class User[S = Pending](Model[S]):
        """Table model with a unique email conflict target."""

        __row_type__: ClassVar[ReadType[User[Row]]]

        email: User.Col[str] = Text(nullable=False, unique=True)

    compiled = (
        insert(User(email="a@example.com")).on_conflict(
            User.email,
            action=DoNothing,
        )
    ).compile()

    expected_sql = 'INSERT INTO "user" ("email") VALUES (?)'
    expected_sql += ' ON CONFLICT ("email") DO NOTHING'
    assert_eq(compiled.sql, expected_sql)
    assert_eq(compiled.params, ("a@example.com",))

    assert_eq(compiled.backend, "sqlite")


@test(mark="fast")
def conflict_do_nothing_rejects_returning_result_shape() -> None:
    """DoNothing cannot satisfy a returning insert's promised row result."""

    class User[S = Pending](Model[S]):
        """Table model with a unique email conflict target."""

        __row_type__: ClassVar[ReadType[User[Row]]]

        email: User.Col[str] = Text(nullable=False, unique=True)

    query = (
        insert(User(email="a@example.com"))
        .on_conflict(User.email, action=DoNothing)
        .returning()
    )

    with assert_raises(QueryCompilationError):
        _ = query.compile()


@test(mark="fast")
def conflict_action_requires_an_assignment() -> None:
    """DoUpdate rejects an action with no columns to update."""

    class User[S = Pending](Model[S]):
        """Table model that anchors the action's owner type."""

        __row_type__: ClassVar[ReadType[User[Row]]]

    with assert_raises(QueryConstructionError):
        _ = DoUpdate[User[Pending]]()  # ty: ignore[no-matching-overload]


@test(mark="fast")
def conflict_action_requires_a_target_column() -> None:
    """on_conflict rejects an action without a conflict target."""

    class User[S = Pending](Model[S]):
        """Table model with one mutable status column."""

        __row_type__: ClassVar[ReadType[User[Row]]]

        status: User.Col[str] = Text(nullable=False)

    with assert_raises(QueryConstructionError):
        _ = insert(User(status="active")).on_conflict(  # ty: ignore[no-matching-overload]
            action=DoUpdate(User.status.to_inserted())
        )


@test(mark="fast")
def conflict_target_requires_an_inserted_model_column() -> None:
    """A conflict target cannot name a column from another model."""

    class User[S = Pending](Model[S]):
        """Inserted table model."""

        __row_type__: ClassVar[ReadType[User[Row]]]

        email: User.Col[str] = Text(nullable=False, unique=True)

    class Account[S = Pending](Model[S]):
        """Unrelated table model."""

        __row_type__: ClassVar[ReadType[Account[Row]]]

        email: Account.Col[str] = Text(nullable=False, unique=True)

    with assert_raises(QueryConstructionError):
        _ = insert(User(email="a@example.com")).on_conflict(
            Account.email,  # ty: ignore[invalid-argument-type]
            action=DoNothing,
        )


@test(mark="fast")
def conflict_update_requires_inserted_model_assignments() -> None:
    """A conflict update cannot assign a column from another model."""

    class User[S = Pending](Model[S]):
        """Inserted table model."""

        __row_type__: ClassVar[ReadType[User[Row]]]

        email: User.Col[str] = Text(nullable=False, unique=True)

    class Account[S = Pending](Model[S]):
        """Unrelated table model."""

        __row_type__: ClassVar[ReadType[Account[Row]]]

        status: Account.Col[str] = Text(nullable=False)

    with assert_raises(QueryConstructionError):
        _ = insert(User(email="a@example.com")).on_conflict(
            User.email,
            action=DoUpdate(Account.status.to("active")),  # ty: ignore[invalid-argument-type]
        )


@test(mark="fast")
def conflict_action_rejects_default_values_insert() -> None:
    """Conflict handling cannot be silently dropped from a default-values insert."""

    class AuditLog[S = Pending](Model[S]):
        """Table model whose insert supplies no explicit columns."""

        __row_type__: ClassVar[ReadType[AuditLog[Row]]]

        id: AuditLog.GenCol[int] = Integer(
            primary_key=True,
            default=PENDING_GENERATION,
        )

    query = insert(AuditLog()).on_conflict(AuditLog.id, action=DoNothing)

    with assert_raises(QueryCompilationError):
        _ = query.compile()


@test(mark="fast")
def inserted_value_rejects_regular_update_context() -> None:
    """An attempted-insert value is only valid inside a conflict update."""

    class User[S = Pending](Model[S]):
        """Table model with one mutable status column."""

        __row_type__: ClassVar[ReadType[User[Row]]]

        status: User.Col[str] = Text(nullable=False)

    query = update(User).set(User.status.to_inserted()).all()

    with assert_raises(QueryCompilationError):
        _ = query.compile()


@test(mark="fast")
def mariadb_conflict_update_uses_duplicate_key_and_values() -> None:
    """MariaDB maps inserted values to its duplicate-key update syntax."""

    class User[S = mariadb.Pending](mariadb.Model[S]):
        """Table model with a unique email conflict target."""

        __row_type__: ClassVar[mariadb.ReadType[User[mariadb.Row]]]

        email: User.Col[str] = mariadb.Text(nullable=False, unique=True)
        name: User.Col[str] = mariadb.Text(nullable=False)
        status: User.Col[str] = mariadb.Text(nullable=False)

    compiled = (
        mariadb.insert(
            User(email="a@example.com", name="Alice", status="inactive")
        ).on_conflict(
            User.email,
            action=mariadb.DoUpdate(
                User.name.to_inserted(),
                User.status.to("active"),
            ),
        )
    ).compile()

    expected_sql = "INSERT INTO `user` (`email`, `name`, `status`) VALUES (%s, %s, %s)"
    expected_sql += " ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `status` = %s"
    assert_eq(compiled.sql, expected_sql)
    assert_eq(compiled.params, ("a@example.com", "Alice", "inactive", "active"))

    assert_eq(compiled.backend, "mariadb")


@test(mark="fast")
def mariadb_conflict_do_nothing_compiles_as_no_op_update() -> None:
    """MariaDB discards a duplicate through an update that changes nothing."""

    class User[S = mariadb.Pending](mariadb.Model[S]):
        """Table model with a unique email conflict target."""

        __row_type__: ClassVar[mariadb.ReadType[User[mariadb.Row]]]

        email: User.Col[str] = mariadb.Text(nullable=False, unique=True)

    compiled = (
        mariadb.insert(User(email="a@example.com")).on_conflict(
            User.email,
            action=mariadb.DoNothing,
        )
    ).compile()

    expected_sql = "INSERT INTO `user` (`email`) VALUES (%s)"
    expected_sql += " ON DUPLICATE KEY UPDATE `email` = `email`"
    assert_eq(compiled.sql, expected_sql)
    assert_eq(compiled.params, ("a@example.com",))

    assert_eq(compiled.backend, "mariadb")


@test(mark="fast")
def sqlite_bulk_conflict_binds_rows_before_update_values() -> None:
    """A conflict literal binds once, after every attempted SQLite row."""

    class User[S = Pending](Model[S]):
        """Batch destination with an attempted value and a literal update."""

        __row_type__: ClassVar[ReadType[User[Row]]]

        email: User.Col[str] = Text(nullable=False, unique=True)
        name: User.Col[str] = Text(nullable=False)
        status: User.Col[str] = Text(nullable=False)

    compiled = (
        insert_many(
            User,
            [
                User(email="a@example.com", name="Alice", status="inactive"),
                User(email="b@example.com", name="Bob", status="invited"),
            ],
        )
        .on_conflict(
            User.email,
            action=DoUpdate(User.name.to_inserted(), User.status.to("active")),
        )
        .compile()
    )

    expected_sql = (
        'INSERT INTO "user" ("email", "name", "status") VALUES (?, ?, ?), (?, ?, ?)'
    )
    expected_sql += ' ON CONFLICT ("email") DO UPDATE SET'
    expected_sql += ' "name" = excluded."name", "status" = ?'
    assert_eq(compiled.sql, expected_sql)
    assert_eq(
        compiled.params,
        (
            "a@example.com",
            "Alice",
            "inactive",
            "b@example.com",
            "Bob",
            "invited",
            "active",
        ),
    )
    assert_eq(compiled.backend, "sqlite")


@test(mark="fast")
def mariadb_bulk_conflict_binds_rows_before_update_values() -> None:
    """A conflict literal binds once, after every attempted MariaDB row."""

    class User[S = mariadb.Pending](mariadb.Model[S]):
        """Native-family batch destination for mixed conflict assignments."""

        __row_type__: ClassVar[mariadb.ReadType[User[mariadb.Row]]]

        email: User.Col[str] = mariadb.Text(nullable=False, unique=True)
        name: User.Col[str] = mariadb.Text(nullable=False)
        status: User.Col[str] = mariadb.Text(nullable=False)

    compiled = (
        mariadb.insert_many(
            User,
            [
                User(email="a@example.com", name="Alice", status="inactive"),
                User(email="b@example.com", name="Bob", status="invited"),
            ],
        )
        .on_conflict(
            User.email,
            action=mariadb.DoUpdate(User.name.to_inserted(), User.status.to("active")),
        )
        .compile()
    )

    expected_sql = "INSERT INTO `user` (`email`, `name`, `status`) VALUES (%s, %s, %s), (%s, %s, %s)"
    expected_sql += " ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `status` = %s"
    assert_eq(compiled.sql, expected_sql)
    assert_eq(
        compiled.params,
        (
            "a@example.com",
            "Alice",
            "inactive",
            "b@example.com",
            "Bob",
            "invited",
            "active",
        ),
    )
    assert_eq(compiled.backend, "mariadb")
