"""Different model declarations must not collapse into one SQL query role."""

from typing import ClassVar

from snektest import Param, assert_eq, assert_raises, test

from snekql import mariadb, sqlite
from tests.query.test_join_compilation import User


@test([Param("people", name="same"), Param("PEOPLE", name="case")], mark="fast")
def correlated_models_cannot_share_a_sql_name(table_name: str) -> None:
    """An inner declaration must not capture references to a distinct outer model."""

    class Person[S = sqlite.Pending](sqlite.Model[S]):
        __tablename__ = "people"
        __row_type__: ClassVar[sqlite.ReadType[Person[sqlite.Row]]]
        id: Person.Col[int] = sqlite.Integer(primary_key=True)

    class Report[S = sqlite.Pending](sqlite.Model[S]):
        __tablename__ = table_name
        __row_type__: ClassVar[sqlite.ReadType[Report[sqlite.Row]]]
        id: Report.Col[int] = sqlite.Integer(primary_key=True)
        manager_id: Report.Col[int] = sqlite.Integer()

    query = sqlite.select(Person).where(
        sqlite.exists(
            sqlite.select(Report.id).where(Report.manager_id.eq_col(Person.id))
        )
    )

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


@test([Param("people", name="same"), Param("PEOPLE", name="case")], mark="fast")
def native_correlated_models_cannot_share_a_sql_name(table_name: str) -> None:
    """An inner declaration must not capture references to a distinct outer model."""

    class Person[S = mariadb.Pending](mariadb.Model[S]):
        __tablename__ = "people"
        __row_type__: ClassVar[mariadb.ReadType[Person[mariadb.Row]]]
        id: Person.Col[int] = mariadb.Integer(primary_key=True)

    class Report[S = mariadb.Pending](mariadb.Model[S]):
        __tablename__ = table_name
        __row_type__: ClassVar[mariadb.ReadType[Report[mariadb.Row]]]
        id: Report.Col[int] = mariadb.Integer(primary_key=True)
        manager_id: Report.Col[int] = mariadb.Integer()

    query = mariadb.select(Person).where(
        mariadb.exists(
            mariadb.select(Report.id).where(Report.manager_id.eq_col(Person.id))
        )
    )

    with assert_raises(mariadb.QueryCompilationError):
        query.compile()


@test(mark="fast")
def same_declaration_can_be_reused_in_an_uncorrelated_subquery() -> None:
    """Repeating one source identity does not invent a distinct outer role."""
    compiled = (
        sqlite.select(User.id)
        .where(User.id.in_subquery(sqlite.select(User.id).where(User.id.gt(2))))
        .compile()
    )

    assert_eq(compiled.params, (2,))
