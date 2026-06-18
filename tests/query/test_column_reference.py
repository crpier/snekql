"""Column-reference rendering contract tests.

All column-name SQL emission routes through one seam in the Query Builder so
the qualification strategy lives in a single place. Today every column renders
as a bare dialect-quoted name (no table qualifier); these tests pin that
contract through the public compile path.
"""

from __future__ import annotations

from snektest import assert_eq, test

from snekql import sqlite
from snekql.sqlite import Fetched, Pending, Text, select
from snekql.sqlite.query import compile_sqlite_select_sql


@test(mark="fast")
def select_columns_render_as_bare_quoted_names() -> None:
    """Projected columns render without a table qualifier."""

    class Widget[S = Pending](sqlite.Model[S, "Widget[Fetched]"]):
        """Model exposing columns for the rendering contract."""

        label: Widget.Col[str] = Text(nullable=False)
        sku: Widget.Col[str] = Text(nullable=False)

    select_sql, select_params = compile_sqlite_select_sql(
        select(Widget.label, Widget.sku).all(),
    )

    assert_eq(select_sql, 'SELECT "label", "sku" FROM "widget"')
    assert_eq(select_params, ())


@test(mark="fast")
def predicate_and_ordering_columns_render_as_bare_quoted_names() -> None:
    """Predicate and ordering columns share the same bare-name rendering seam."""

    class Widget[S = Pending](sqlite.Model[S, "Widget[Fetched]"]):
        """Model exposing columns used in WHERE and ORDER BY."""

        label: Widget.Col[str] = Text(nullable=False)
        sku: Widget.Col[str] = Text(nullable=False)

    select_sql, select_params = compile_sqlite_select_sql(
        select(Widget.label).where(Widget.sku.eq("A1")).order_by(Widget.label.asc()),
    )

    assert_eq(
        select_sql,
        'SELECT "label" FROM "widget" WHERE ("sku" = ?) ORDER BY "label" ASC',
    )
    assert_eq(select_params, ("A1",))
