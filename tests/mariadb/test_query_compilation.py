"""MariaDB query compilation seam tests."""

from __future__ import annotations

from snektest import assert_eq, test

from snekql import Fetched, Pending, insert, mariadb, select, update
from snekql.mariadb.query import compile_mariadb_select_sql, compile_mariadb_write_sql


@test(mark="fast")
def mariadb_select_compilation_quotes_identifiers_with_backticks() -> None:
    """MariaDB select SQL quotes table and column identifiers with backticks."""

    class KeywordModel[S = Pending](mariadb.Model[S, "KeywordModel[Fetched]"]):
        """Model using SQL keywords to make identifier quoting observable."""

        __tablename__ = "select"
        where: KeywordModel.Col[str] = mariadb.Text(nullable=False)

    select_sql, select_params = compile_mariadb_select_sql(
        select(KeywordModel.where).all(),
    )

    assert_eq(select_sql, "SELECT `where` FROM `select`")
    assert_eq(select_params, ())


@test(mark="fast")
def mariadb_select_compilation_uses_percent_s_placeholders() -> None:
    """MariaDB select predicates use driver-style `%s` placeholders."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Model used to compile one equality predicate."""

        status: User.Col[str] = mariadb.Text(nullable=False)

    select_sql, select_params = compile_mariadb_select_sql(
        select(User.status).where(User.status.eq("active")),
    )

    assert_eq(select_sql, "SELECT `status` FROM `user` WHERE (`status` = %s)")
    assert_eq(select_params, ("active",))


@test(mark="fast")
def mariadb_select_compilation_renders_in_predicates() -> None:
    """MariaDB select SQL expands IN predicates into one placeholder per value."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Model used to compile an IN predicate."""

        status: User.Col[str] = mariadb.Text(nullable=False)

    select_sql, select_params = compile_mariadb_select_sql(
        select(User.status).where(User.status.in_("active", "paused")),
    )

    assert_eq(select_sql, "SELECT `status` FROM `user` WHERE (`status` IN (%s, %s))")
    assert_eq(select_params, ("active", "paused"))


@test(mark="fast")
def mariadb_select_compilation_renders_result_windowing() -> None:
    """MariaDB select SQL renders ordering and pagination clauses."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Model used to compile result-windowing clauses."""

        email: User.Col[str] = mariadb.Text(nullable=False)

    select_sql, select_params = compile_mariadb_select_sql(
        select(User.email).all().order_by(User.email.desc()).limit(2).offset(1),
    )

    assert_eq(
        select_sql,
        "SELECT `email` FROM `user` ORDER BY `email` DESC LIMIT %s OFFSET %s",
    )
    assert_eq(select_params, (2, 1))


@test(mark="fast")
def mariadb_update_compilation_renders_predicated_assignments() -> None:
    """MariaDB update SQL renders SET assignments with a WHERE predicate."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Model used to compile one update statement."""

        enabled: User.Col[bool] = mariadb.Boolean(nullable=False)
        status: User.Col[str] = mariadb.Text(nullable=False)

    update_sql, update_params = compile_mariadb_write_sql(
        update(User).set(User.enabled.to(False)).where(User.status.ne("old")),
    )

    assert_eq(update_sql, "UPDATE `user` SET `enabled` = %s WHERE (`status` != %s)")
    assert_eq(update_params, (0, "old"))


@test(mark="fast")
def mariadb_insert_compilation_encodes_boolean_values_with_mariadb_codecs() -> None:
    """MariaDB insert SQL delegates parameter encoding to MariaDB column codecs."""

    class FeatureFlag[S = Pending](mariadb.Model[S, "FeatureFlag[Fetched]"]):
        """Model with a boolean column whose encoded value differs from Python."""

        enabled: FeatureFlag.Col[bool] = mariadb.Boolean(nullable=False)

    insert_sql, insert_params = compile_mariadb_write_sql(
        insert(FeatureFlag(enabled=True)),
    )

    assert_eq(insert_sql, "INSERT INTO `feature_flag` (`enabled`) VALUES (%s)")
    assert_eq(insert_params, (1,))
