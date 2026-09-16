"""General ON predicates through public Query Builder compilation."""

from uuid import UUID

from snektest import Param, assert_eq, assert_raises, assert_true, test

from snekql import sqlite
from tests.query.test_join_compilation import Order, User
from tests.query.test_join_validation import Item


@test(mark="fast")
def compound_on_preserves_sql_binding_order() -> None:
    """ON values precede WHERE values without requiring an FK condition."""
    compiled = (
        sqlite.select(User.email, Order.note)
        .join(
            Order,
            on=Order.user_id.eq_col(User.id) & Order.note.ne("hidden"),
        )
        .where(User.email.eq("reader"))
        .compile()
    )

    assert_eq(
        compiled.sql,
        'SELECT "user"."email", "order"."note" FROM "user" '
        'INNER JOIN "order" ON ("order"."user_id" = "user"."id") AND ("order"."note" != ?) '
        'WHERE ("user"."email" = ?)',
    )
    assert_eq(compiled.params, ("hidden", "reader"))


@test(mark="fast")
def on_cannot_reference_a_later_join() -> None:
    """The final FROM graph cannot legitimize a forward reference in ON."""
    query = (
        sqlite.select(User)
        .join(Order, on=Order.user_id.eq_col(Item.order_id))
        .join(Item, on=Item.order_id.eq_col(Order.id))
        .all()
    )

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


@test(mark="fast")
def on_rejects_an_unjoined_predicate_owner() -> None:
    """Dynamic callers cannot filter ON with an unrelated table's column."""
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(User).join(Order, on=Item.order_id.eq(1))  # ty: ignore[no-matching-overload]


@test(mark="fast")
def on_rejects_aggregate_filters() -> None:
    """Row joins do not admit group-level aggregate conditions."""
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(User).join(Order, on=Order.id.count().gt(1))


@test(mark="fast")
def on_can_filter_only_the_joined_table() -> None:
    """Explicit predicates need not claim an FK relationship between tables."""
    compiled = (
        sqlite.select(User).join(Order, on=Order.note.eq("visible")).all().compile()
    )

    assert_true('INNER JOIN "order" ON "order"."note" = ?' in compiled.sql)
    assert_eq(compiled.params, ("visible",))


@test(mark="fast")
def on_subquery_can_correlate_to_the_joined_table() -> None:
    """An EXISTS condition sees the table introduced by its ON clause."""
    compiled = (
        sqlite.select(User)
        .join(
            Order,
            on=Order.user_id.eq_col(User.id)
            & sqlite.exists(
                sqlite.select(Item.order_id).where(Item.order_id.eq_col(Order.id))
            ),
        )
        .all()
        .compile()
    )

    assert_true('"item"."order_id" = "order"."id"' in compiled.sql)


@test(mark="fast")
def on_subquery_cannot_correlate_to_a_later_join() -> None:
    """Nested SELECTs inherit the ON prefix, not the final join graph."""
    query = (
        sqlite.select(User)
        .join(
            Order,
            on=sqlite.exists(
                sqlite.select(User.id).where(User.id.eq_col(Item.order_id))
            ),
        )
        .join(Item, on=Item.order_id.eq_col(Order.id))
        .all()
    )

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


@test(
    [Param("and", name="and"), Param("or", name="or"), Param("not", name="not")],
    mark="fast",
)
def on_rejects_unjoined_owners_in_composed_predicates(operator: str) -> None:
    """Nested boolean operators do not bypass ON scope checks."""
    valid = Order.user_id.eq_col(User.id)
    invalid = Item.order_id.eq(1)
    conditions = {"and": valid & invalid, "or": valid | invalid, "not": ~invalid}

    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(User).join(Order, on=conditions[operator])  # ty: ignore[no-matching-overload]


@test(mark="fast")
def on_bindings_follow_projection_bindings() -> None:
    """Scalar SELECT bindings precede ON, WHERE, and pagination bindings."""
    compiled = (
        sqlite.select(
            User.id,
            sqlite.scalar(sqlite.select(Item.order_id).where(Item.order_id.eq(7))),
        )
        .join(Order, on=Order.user_id.eq_col(User.id) & Order.note.eq("on"))
        .where(User.email.eq("where"))
        .limit(5)
        .offset(2)
        .compile()
    )

    assert_eq(compiled.params, (7, "on", "where", 5, 2))


@test(mark="fast")
def multiple_on_clauses_bind_in_join_order() -> None:
    """Each joined table contributes its bindings at its own SQL position."""
    compiled = (
        sqlite.select(User)
        .join(Order, on=Order.user_id.eq_col(User.id) & Order.note.eq("first"))
        .left_join(Item, on=Item.order_id.eq_col(Order.id) & Item.id.gt(4))
        .where(User.email.eq("last"))
        .compile()
    )

    assert_eq(compiled.params, ("first", 4, "last"))


@test(mark="fast")
def on_values_use_the_column_codec() -> None:
    """A logical UUID is encoded for SQLite TEXT rather than bound as an object."""

    class Token[S = sqlite.Pending](sqlite.Model[S, "Token[sqlite.Fetched]"]):
        token: Token.Col[UUID] = sqlite.Text(primary_key=True)

    compiled = (
        sqlite.select(User)
        .join(Token, on=Token.token.eq(UUID("12345678-1234-5678-1234-567812345678")))
        .all()
        .compile()
    )

    assert_eq(compiled.params, ("12345678-1234-5678-1234-567812345678",))


@test(mark="fast")
def nested_on_can_compare_to_an_enclosing_query() -> None:
    """The ON prefix retains enclosing scopes for correlated right operands."""
    compiled = (
        sqlite.select(User.id)
        .where(
            sqlite.exists(
                sqlite.select(Order.id)
                .join(Item, on=Item.order_id.eq_col(User.id))
                .all()
            )
        )
        .compile()
    )

    assert_true('INNER JOIN "item" ON "item"."order_id" = "user"."id"' in compiled.sql)
