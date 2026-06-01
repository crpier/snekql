"""MariaDB backend namespace declaration tests."""

from __future__ import annotations

from typing import Any, cast

from snektest import (
    assert_eq,
    assert_in,
    assert_isinstance,
    assert_ne,
    assert_raises,
    test,
)

import snekql
from snekql import DatabaseRuntimeError


@test()
def mariadb_namespace_exports_backend_specific_names() -> None:
    """The MariaDB namespace exposes distinct declaration types."""

    assert_in("mariadb", snekql.__all__)
    assert_in("Config", snekql.mariadb.__all__)
    assert_ne(snekql.mariadb.Model, snekql.sqlite.Model)
    assert_ne(snekql.mariadb.Integer, snekql.sqlite.Integer)
    assert_ne(snekql.mariadb.Text, snekql.sqlite.Text)

    class MariadbUser(
        snekql.mariadb.Model[snekql.Pending, "MariadbUser[snekql.Fetched]"]
    ):
        """MariaDB table model declared through the MariaDB namespace."""

        id: MariadbUser.GenCol[int] = snekql.mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=snekql.MISSING,
        )
        email: MariadbUser.Col[str] = snekql.mariadb.Text(nullable=False)

    assert_isinstance(MariadbUser.id, snekql.mariadb.Attr)
    assert_isinstance(MariadbUser.email.eq("alice@example.com"), snekql.Predicate)


@test()
def mariadb_config_validates_connection_and_pool_settings() -> None:
    """MariaDB config rejects invalid declaration-time settings."""

    config = snekql.mariadb.Config(
        database="app",
        host="127.0.0.1",
        password="secret",
        port=3306,
        user="snekql",
    )

    assert_eq(config.host, "127.0.0.1")
    assert_eq(config.port, 3306)
    assert "secret" not in repr(config)

    config_factory = cast("Any", snekql.mariadb.Config)

    with assert_raises(DatabaseRuntimeError):
        _ = config_factory(database="app", host="", user="snekql")

    with assert_raises(DatabaseRuntimeError):
        _ = config_factory(database="app", port=0, user="snekql")

    with assert_raises(DatabaseRuntimeError):
        _ = config_factory(database="app", port=70000, user="snekql")

    with assert_raises(DatabaseRuntimeError):
        _ = config_factory(database="", user="snekql")

    with assert_raises(DatabaseRuntimeError):
        _ = config_factory(database="app", pool_size=True, user="snekql")
