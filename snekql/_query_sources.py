"""Query source fields, separate from schema-owned column declarations."""

lazy from typing import Any

lazy from snekql._aliases import require_query_source as require_table_source
lazy from snekql._cte import _Cte, _CteOutput
lazy from snekql._query_state import (
    require_column_model,
    require_column_name,
    require_field,
)
lazy from snekql.model import Table
lazy from snekql.storage import Attr


def require_query_source(value: object) -> type[Table[Any]]:
    """Normalize a table, table alias or query-only named reference."""
    return (
        value.__query_source__()
        if isinstance(value, _Cte)
        else require_table_source(value)
    )


def require_grouping_column(
    value: object,
) -> Attr[Any, Any, Any, Any, Any] | _CteOutput[Any, Any, Any]:
    """Grouping admits schema columns and readonly derived output references."""
    return value if isinstance(value, _CteOutput) else require_field(value)


def grouping_key(value: object) -> tuple[type[Table[Any]], str | int]:
    """A source identity and output position identify repeated CTE references."""
    column = require_grouping_column(value)
    if isinstance(column, _CteOutput):
        return column.relation, column.position
    return require_column_model(column), require_column_name(column)
