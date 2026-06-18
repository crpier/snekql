"""MariaDB JSON path operators: the first open-AST dialect expression (ADR 0004).

These exercise the core open-AST seam end to end through the MariaDB dialect:
``json_extract_int`` composes as a ``WHERE`` operand and as a typed ``SELECT``
projection, the core compiles it without naming the leaf, and materialization
decodes it through the leaf-owned ``__decode__``.
"""

from __future__ import annotations

from snektest import assert_eq, test

from snekql import mariadb
from snekql.mariadb import Fetched, Pending, select
from snekql.mariadb.query import (
    compile_mariadb_select_sql,
    materialize_mariadb_select_row,
)


class _Profiled[S = Pending](mariadb.Model[S, "_Profiled[Fetched]"]):
    """MariaDB model with a JSON column carrying the dialect operators."""

    name: _Profiled.Col[str] = mariadb.Text(nullable=False)
    profile: _Profiled.JsonCol[dict[str, object]] = mariadb.Json(nullable=False)


@test(mark="fast")
def json_extract_int_renders_as_a_where_operand() -> None:
    """A JSON path operator composes as a predicate operand the core renders."""

    select_sql, select_params = compile_mariadb_select_sql(
        select(_Profiled.name).where(
            _Profiled.profile.json_extract_int("$.age").gt(18)
        ),
    )

    assert_eq(
        select_sql,
        "SELECT `name` FROM `_profiled` WHERE (JSON_EXTRACT(`profile`, '$.age') > %s)",
    )
    assert_eq(select_params, (18,))


@test(mark="fast")
def json_extract_int_composes_with_core_predicates() -> None:
    """A dialect predicate composes with core predicates via ``&``."""

    combined = _Profiled.name.eq("ada") & _Profiled.profile.json_extract_int(
        "$.age",
    ).gt(18)
    select_sql, select_params = compile_mariadb_select_sql(
        select(_Profiled.name).where(combined),
    )

    where_clause = "WHERE ((`name` = %s) AND (JSON_EXTRACT(`profile`, '$.age') > %s))"
    expected = f"SELECT `name` FROM `_profiled` {where_clause}"
    assert_eq(select_sql, expected)
    assert_eq(select_params, ("ada", 18))


@test(mark="fast")
def json_extract_int_renders_as_a_projection() -> None:
    """A JSON path operator projects in the select list via the projection seam."""

    select_sql, select_params = compile_mariadb_select_sql(
        select(_Profiled.profile.json_extract_int("$.age")).all(),
    )

    assert_eq(
        select_sql,
        "SELECT JSON_EXTRACT(`profile`, '$.age') FROM `_profiled`",
    )
    assert_eq(select_params, ())


@test(mark="fast")
def json_extract_int_decodes_a_projected_value() -> None:
    """Materialization decodes the projected scalar through the leaf decode seam."""

    query = select(_Profiled.profile.json_extract_int("$.age")).all()
    decoded = materialize_mariadb_select_row(query, ("41",))

    assert_eq(decoded, 41)


@test(mark="fast")
def json_extract_int_decodes_in_a_heterogeneous_projection() -> None:
    """A core column and a dialect expression each decode through their own seam."""

    query = select(
        _Profiled.name,
        _Profiled.profile.json_extract_int("$.age"),
    ).all()
    decoded = materialize_mariadb_select_row(query, ("ada", b"41"))

    assert_eq(decoded, ("ada", 41))
