"""MariaDB query compilation seam tests."""

from __future__ import annotations

from snektest import assert_eq, test

import snekql.mariadb.query as mariadb_query
from snekql import MISSING, Pending, insert, mariadb, select, update
from snekql.mariadb.query import compile_mariadb_select_sql, compile_mariadb_write_sql


@test(mark="fast")
def mariadb_query_compiler_uses_dialect_without_sqlite_translation() -> None:
    """MariaDB SQL compilation is direct, not translated from SQLite SQL."""

    assert_eq(hasattr(mariadb_query, "_translate_sqlite_sql"), False)
    assert_eq(hasattr(mariadb_query, "compile_select_sql"), False)
    assert_eq(hasattr(mariadb_query, "compile_write_sql"), False)


@test(mark="fast")
def mariadb_query_compilation_renders_backend_sql_and_codecs_directly() -> None:
    """MariaDB compilation owns quotes, placeholders, and value codecs."""

    class User[S = Pending](mariadb.Model[S, "User[object]"]):
        """MariaDB model used by direct dialect-compilation checks."""

        __tablename__ = "select"
        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        enabled: User.Col[bool] = mariadb.Boolean(nullable=False)
        status: User.Col[str] = mariadb.Text(nullable=False)
        where: User.Col[str] = mariadb.Text(nullable=False)

    select_sql, select_params = compile_mariadb_select_sql(
        select(User.where)
        .where(User.enabled.eq(True), User.status.in_("active", "paused"))
        .order_by(User.where.desc())
        .limit(2)
        .offset(1),
    )
    update_sql, update_params = compile_mariadb_write_sql(
        update(User).set(User.enabled.to(False)).where(User.where.ne("old")),
    )
    insert_sql, insert_params = compile_mariadb_write_sql(
        insert(User(enabled=True, status="active", where="new")),
    )

    expected_select_sql = "".join(
        (
            "SELECT `where` FROM `select` WHERE (`enabled` = %s) ",
            "AND (`status` IN (%s, %s)) ORDER BY `where` DESC LIMIT %s OFFSET %s",
        )
    )
    assert_eq(select_sql, expected_select_sql)
    assert_eq(select_params, (1, "active", "paused", 2, 1))
    assert_eq(update_sql, "UPDATE `select` SET `enabled` = %s WHERE (`where` != %s)")
    assert_eq(update_params, (0, "old"))
    assert_eq(
        insert_sql,
        "INSERT INTO `select` (`enabled`, `status`, `where`) VALUES (%s, %s, %s)",
    )
    assert_eq(insert_params, (1, "active", "new"))
