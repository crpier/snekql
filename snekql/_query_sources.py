"""Query source fields, separate from schema-owned column declarations."""

from typing import Any

from snekql._aliases import require_query_source as require_table_source
from snekql._cte import _Cte, _CteOutput, _CtePresence, _CteRelation
from snekql._query_state import (
    Selectable,
    require_column_model,
    require_column_name,
    require_field,
)
from snekql.model import Table, require_model_columns
from snekql.storage import Attr


def require_query_source(value: object) -> type[Table[Any]]:
    """Normalize a table, table alias or query-only named reference."""
    return (
        value.__query_source__()
        if isinstance(value, _Cte)
        else require_table_source(value)
    )


def query_fields(
    source: type[Table[Any]], *, presence: bool = False
) -> tuple[Selectable, ...]:
    """Expand visible query fields without manufacturing schema Attr metadata."""
    if issubclass(source, _CteRelation):
        outputs: tuple[Selectable, ...] = tuple(
            _CteOutput[Any, Any, Any](position=position, relation=source)
            for position in range(len(source.definition.state.fields))
        )
        return (*outputs, _CtePresence(source)) if presence else outputs
    return tuple(require_model_columns(source).values())


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
