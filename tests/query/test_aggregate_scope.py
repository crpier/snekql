"""Aggregates outside SELECT still cannot expose an ungrouped row value."""

from typing import ClassVar

from snektest import Param, assert_eq, assert_raises, test

from snekql import mariadb, sqlite
from tests.query.test_join_compilation import Order, User


@test([Param("having", name="having"), Param("ordering", name="ordering")], mark="fast")
def hidden_aggregate_rejects_an_ungrouped_projection(clause: str) -> None:
    """HAVING or ORDER BY does not make a bare projected identifier a group key."""
    query = sqlite.select(User.id)
    query = (
        query.having(User.id.count().gt(1))
        if clause == "having"
        else query.order_by(User.id.count().desc())
    )

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


class NativeUser[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[NativeUser[mariadb.Row]]]
    id: NativeUser.Col[int] = mariadb.Integer(primary_key=True)


@test([Param("having", name="having"), Param("ordering", name="ordering")], mark="fast")
def native_hidden_aggregate_rejects_an_ungrouped_projection(clause: str) -> None:
    """Server permissiveness must not pick an arbitrary row for a group."""
    query = mariadb.select(NativeUser.id)
    query = (
        query.having(~(NativeUser.id.count().lt(1) | NativeUser.id.count().gt(5)))
        if clause == "having"
        else query.order_by(NativeUser.id.count().desc())
    )
    with assert_raises(mariadb.QueryCompilationError):
        query.compile()


@test(mark="fast")
def grouping_allows_aggregate_only_in_having_or_ordering() -> None:
    """An explicit group key makes both otherwise-hidden aggregates well-defined."""
    compiled = (
        sqlite.select(User.id)
        .group_by(User.id)
        .having(User.id.count().gt(1))
        .order_by(User.id.count().desc())
        .compile()
    )
    assert_eq(compiled.params, (1,))


@test(mark="fast")
def grouped_query_rejects_ungrouped_ordering() -> None:
    """Selecting valid groups does not permit ordering by an arbitrary input row."""
    query = (
        sqlite.select(User.email, User.id.count())
        .group_by(User.email)
        .order_by(User.id.asc())
    )
    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


@test(mark="fast")
def json_projection_cannot_hide_an_ungrouped_column() -> None:
    """A dialect expression must expose the same grouping dependencies as a column."""

    class Document[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Document[mariadb.Row]]]
        payload: Document.JsonCol[dict[str, int]] = mariadb.Json()

    query = mariadb.select(
        Document.payload.json_extract_int("$.score"), Document.count_all()
    )

    with assert_raises(mariadb.QueryCompilationError):
        query.compile()


@test(mark="fast")
def grouped_json_projection_retains_its_path_binding() -> None:
    """Grouping the source document permits JSON extraction without losing parameters."""

    class Document[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Document[mariadb.Row]]]
        payload: Document.JsonCol[dict[str, int]] = mariadb.Json()

    compiled = (
        mariadb.select(
            Document.payload.json_extract_int("$.score"), Document.count_all()
        )
        .group_by(Document.payload)
        .compile()
    )
    assert_eq(compiled.params, ("$.score",))


@test(mark="fast")
def scalar_projection_cannot_read_an_ungrouped_outer_column() -> None:
    """Correlating inside a scalar SELECT cannot bypass the outer GROUP BY."""
    query = sqlite.select(
        User.email,
        sqlite.scalar(
            sqlite.select(Order.id).where(Order.user_id.eq_col(User.id)).limit(1)
        ),
        User.count_all(),
    ).group_by(User.email)
    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


@test(mark="fast")
def scalar_projection_can_read_the_outer_group_key() -> None:
    """Correlation remains valid when the referenced value is constant per group."""
    compiled = (
        sqlite.select(
            User.id,
            sqlite.scalar(
                sqlite.select(Order.id).where(Order.user_id.eq_col(User.id)).limit(1)
            ),
            User.count_all(),
        )
        .group_by(User.id)
        .compile()
    )
    assert_eq(compiled.params, (1,))


@test(mark="fast")
def having_subquery_cannot_read_an_ungrouped_outer_column() -> None:
    """An aggregate comparison cannot conceal a row-level correlation in HAVING."""
    matching_order = sqlite.scalar(
        sqlite.select(Order.id).where(Order.user_id.eq_col(User.id)).limit(1)
    )
    query = (
        sqlite.select(User.email, User.count_all())
        .group_by(User.email)
        .having(~(User.count_all().eq(0) | User.count_all().lt_col(matching_order)))
    )
    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


@test(mark="fast")
def where_correlation_runs_before_grouping() -> None:
    """A row filter may read an ungrouped identifier before the grouping step."""
    compiled = (
        sqlite.select(User.email, User.count_all())
        .where(
            sqlite.exists(sqlite.select(Order.id).where(Order.user_id.eq_col(User.id)))
        )
        .group_by(User.email)
        .compile()
    )
    assert_eq(compiled.params, ())


@test(mark="fast")
def uncorrelated_scalar_does_not_require_outer_group_keys() -> None:
    """A nested query's own identifier is not a column in the outer grouping."""
    compiled = (
        sqlite.select(
            User.email,
            sqlite.scalar(sqlite.select(Order.id).limit(1)),
            User.count_all(),
        )
        .group_by(User.email)
        .compile()
    )
    assert_eq(compiled.params, (1,))


@test(mark="fast")
def deeply_nested_scalar_cannot_capture_ungrouped_outer_values() -> None:
    """A second nested SELECT must not conceal the outer row-level dependency."""

    class DeepRole:
        pass

    deep = sqlite.alias(Order, DeepRole, name="deep_order")
    inner = sqlite.select(deep.column(Order.id)).where(
        deep.column(Order.user_id).eq_col(User.id)
    )
    middle = sqlite.select(Order.id).where(Order.id.in_subquery(inner)).limit(1)
    query = sqlite.select(User.email, sqlite.scalar(middle), User.count_all()).group_by(
        User.email
    )

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()
