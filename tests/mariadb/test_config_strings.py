"""MariaDB rejects invalid connection names before attempting driver work."""

from snektest import Param, assert_raises, test

from snekql import mariadb


@test(
    [
        Param(None, name="missing"),
        Param(123, name="integer"),
        Param(b"account", name="bytes"),
    ],
    mark="fast",
)
def invalid_user_has_a_domain_error(user: object) -> None:
    """Dynamic configuration must not leak AttributeError or accept bytes."""
    with assert_raises(mariadb.DatabaseRuntimeError):
        mariadb.Config(database="app", user=user)  # ty: ignore[invalid-argument-type]


@test(mark="fast")
def invalid_database_has_a_domain_error() -> None:
    """Missing database names fail at configuration, not string operations."""
    with assert_raises(mariadb.DatabaseRuntimeError):
        mariadb.Config(database=None, user="account")  # ty: ignore[invalid-argument-type]


@test(mark="fast")
def invalid_host_has_a_domain_error() -> None:
    """Missing hosts fail at configuration, not string operations."""
    with assert_raises(mariadb.DatabaseRuntimeError):
        mariadb.Config(database="app", user="account", host=None)  # ty: ignore[invalid-argument-type]


@test(mark="fast")
def invalid_charset_has_a_domain_error() -> None:
    """Byte strings cannot pass validation as charset names."""
    with assert_raises(mariadb.DatabaseRuntimeError):
        mariadb.Config(database="app", user="account", charset=b"utf8mb4")  # ty: ignore[invalid-argument-type]
