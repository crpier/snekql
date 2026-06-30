"""Property-based tests for query compilation.

The example-based seam tests pin exact SQL for a handful of shapes. These assert
the structural invariants that must hold for *any* compilable query, across query
shapes composed by Hypothesis (projection, a conjunction of predicates of every
kind, distinct, ordering, limit/offset, and the SET/WHERE of writes):

* **Full parameterization** -- the number of placeholder tokens in the compiled
  SQL equals the number of bound parameters. This is the injection-safety
  guarantee: every value reaches the driver as a bound parameter, never spliced
  into the SQL text. It is also the invariant ``inspect_query_sql`` relies on to
  inline parameters unambiguously.
* **Determinism** -- compiling the same query twice yields identical SQL and
  parameters (no dict/set ordering leaks into the output).

The shared compiler in ``snekql._query_compile`` does the work for every backend;
the dialect only supplies the placeholder token and quoting. Exercising it
through the SQLite dialect therefore covers the compilation logic itself, and a
couple of focused properties pin the per-clause parameter accounting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from hypothesis import settings
from hypothesis import strategies as st
from snektest import assert_eq, assert_true, test_hypothesis

from snekql.sqlite import (
    PENDING_GENERATION,
    Fetched,
    Integer,
    Model,
    Pending,
    Real,
    Text,
    delete,
    select,
    update,
)
from snekql.sqlite.query import compile_sqlite_select_sql, compile_sqlite_write_sql

if TYPE_CHECKING:
    from snekql.expressions import Predicate
    from snekql.storage import Assignment, Attr

# SQLite binds every value as a "?" placeholder; compiled SQL carries no string
# literals and quotes identifiers with double quotes, so a "?" in the SQL can
# only be a placeholder (the model's identifiers below never contain one).
_PLACEHOLDER = "?"

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


class Widget[S = Pending](Model[S, "Widget[Fetched]"]):
    """A small multi-type model the generated queries are composed against."""

    id: Widget.GenCol[int] = Integer(primary_key=True, default=PENDING_GENERATION)
    name: Widget.Col[str] = Text(nullable=False)
    qty: Widget.Col[int] = Integer(nullable=False)
    price: Widget.Col[float] = Real(nullable=False)


_ALL_COLUMNS: tuple[Attr[Any, Any, Any, Any, Any], ...] = (
    Widget.id,
    Widget.name,
    Widget.qty,
    Widget.price,
)

_int_values = st.integers(min_value=_INT64_MIN, max_value=_INT64_MAX)
_text_values = st.text(st.characters(codec="utf-8"), max_size=20)
_float_values = st.floats(allow_nan=False, allow_infinity=False)


def _predicates_for(
    column: Attr[Any, Any, Any, Any, Any],
    values: st.SearchStrategy[Any],
    *,
    text: bool,
) -> st.SearchStrategy[Predicate[Any]]:
    """Every predicate kind valid for ``column``, as one combined strategy.

    Built from typed combinators over the column's bound methods rather than
    ``getattr`` so the generated predicates stay statically typed. ``like`` /
    ``not_like`` are added only for the text column.
    """

    operand_lists = st.lists(values, min_size=1, max_size=4)
    options: list[st.SearchStrategy[Predicate[Any]]] = [
        values.map(column.eq),
        values.map(column.ne),
        values.map(column.gt),
        values.map(column.gte),
        values.map(column.lt),
        values.map(column.lte),
        operand_lists.map(lambda operands: column.in_(*operands)),
        operand_lists.map(lambda operands: column.not_in(*operands)),
        st.tuples(values, values).map(
            # `column`/`values` are deliberately `Any`-typed test infrastructure,
            # so `between` resolves to its None-rejecting overload here.
            lambda bounds: column.between(*bounds),  # pyright: ignore[reportDeprecated]
        ),
        st.just(column.is_null()),
        st.just(column.is_not_null()),
    ]
    if text:
        options.append(_text_values.map(column.like))
        options.append(_text_values.map(column.not_like))
    return st.one_of(options)


_PREDICATES = st.one_of(
    _predicates_for(Widget.id, _int_values, text=False),
    _predicates_for(Widget.qty, _int_values, text=False),
    _predicates_for(Widget.price, _float_values, text=False),
    _predicates_for(Widget.name, _text_values, text=True),
)


@st.composite
def _select_queries(draw: st.DrawFn) -> Any:
    """Compose an arbitrary compilable SELECT over :class:`Widget`."""

    projection = draw(st.lists(st.sampled_from(_ALL_COLUMNS), min_size=1, max_size=5))
    query = cast("Any", select(*projection))
    predicates = draw(st.lists(_PREDICATES, max_size=4))
    # A SELECT needs either an explicit all() or at least one predicate.
    query = query.where(*predicates) if predicates else query.all()
    if draw(st.booleans()):
        query = query.distinct()
    order_columns = draw(st.lists(st.sampled_from(_ALL_COLUMNS), max_size=3))
    if order_columns:
        orderings = [
            column.desc() if draw(st.booleans()) else column.asc()
            for column in order_columns
        ]
        query = query.order_by(*orderings)
    limit = draw(st.none() | st.integers(min_value=0, max_value=1000))
    if limit is not None:
        query = query.limit(limit)
    offset = draw(st.none() | st.integers(min_value=0, max_value=1000))
    if offset is not None:
        query = query.offset(offset)
    return query


@settings(deadline=None, max_examples=300)
@test_hypothesis(_select_queries(), mark="fast")
def every_value_is_bound_as_a_placeholder(query: Any) -> None:
    """Compiled SQL has exactly one placeholder per bound parameter."""

    sql, params = compile_sqlite_select_sql(query)
    assert_eq(sql.count(_PLACEHOLDER), len(params))


@settings(deadline=None, max_examples=200)
@test_hypothesis(_select_queries(), mark="fast")
def compilation_is_deterministic(query: Any) -> None:
    """Compiling the same query twice yields identical SQL and parameters."""

    first = compile_sqlite_select_sql(query)
    second = compile_sqlite_select_sql(query)
    assert_eq(first, second)
    sql, _ = first
    assert_true(sql.startswith("SELECT"))


@settings(deadline=None)
@test_hypothesis(st.lists(_int_values, min_size=1, max_size=12), mark="fast")
def in_predicate_binds_one_placeholder_per_value(values: list[int]) -> None:
    """An IN predicate expands to exactly one placeholder per supplied value."""

    sql, params = compile_sqlite_select_sql(
        select(Widget.id).where(Widget.qty.in_(*values)),
    )
    assert_eq(len(params), len(values))
    assert_eq(sql.count(_PLACEHOLDER), len(values))


@settings(deadline=None)
@test_hypothesis(
    st.integers(min_value=0, max_value=1000),
    st.integers(min_value=0, max_value=1000),
    mark="fast",
)
def limit_and_offset_bind_their_values_in_order(limit: int, offset: int) -> None:
    """LIMIT and OFFSET bind their integers as trailing parameters, in order."""

    sql, params = compile_sqlite_select_sql(
        select(Widget.id).all().limit(limit).offset(offset),
    )
    assert_eq(params, (limit, offset))
    assert_eq(sql.count(_PLACEHOLDER), 2)


def _assignments_for(
    column: Attr[Any, Any, Any, Any, Any],
    values: st.SearchStrategy[Any],
) -> st.SearchStrategy[Assignment[Any]]:
    return values.map(column.to)


# A SET assignment for any of the non-PK, value-bearing columns. Duplicate
# targets are allowed -- the compiler emits both and the parameter accounting
# still has to balance, which is exactly what the property checks.
_ASSIGNMENTS = st.one_of(
    _assignments_for(Widget.name, _text_values),
    _assignments_for(Widget.qty, _int_values),
    _assignments_for(Widget.price, _float_values),
)


@settings(deadline=None, max_examples=200)
@test_hypothesis(
    st.lists(_ASSIGNMENTS, min_size=1, max_size=3),
    st.lists(_PREDICATES, max_size=3),
    mark="fast",
)
def update_binds_every_set_and_where_value(
    assignments: list[Assignment[Any]],
    predicates: list[Predicate[Any]],
) -> None:
    """UPDATE binds one placeholder per SET assignment plus every WHERE value."""

    query = update(Widget).set(*assignments)
    query = query.where(*predicates) if predicates else query.all()
    sql, params = compile_sqlite_write_sql(query)
    assert_eq(sql.count(_PLACEHOLDER), len(params))


@settings(deadline=None, max_examples=200)
@test_hypothesis(st.lists(_PREDICATES, max_size=4), mark="fast")
def delete_binds_every_where_value(predicates: list[Predicate[Any]]) -> None:
    """DELETE binds exactly one placeholder per WHERE parameter."""

    query = delete(Widget)
    query = query.where(*predicates) if predicates else query.all()
    sql, params = compile_sqlite_write_sql(query)
    assert_eq(sql.count(_PLACEHOLDER), len(params))
