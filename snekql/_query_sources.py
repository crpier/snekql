"""Query source fields, separate from schema-owned column declarations."""

from dataclasses import dataclass
from typing import Any

from snekql._aliases import require_query_source as require_table_source
from snekql._cte import _Cte, _CteOutput, _CtePresence, _CteRelation
from snekql._dialect_expr import CompileCtx
from snekql._query_state import (
    Selectable,
    require_column_model,
    require_column_name,
    require_field,
)
from snekql.model import Table, require_model_columns, require_model_table_name
from snekql.storage import Attr


@dataclass(frozen=True, slots=True)
class _TablePresence:
    """A derived table's marker distinguishes a matched all-NULL payload."""

    source: type[Table[Any]]
    name: str

    def __owner_model__(self) -> type[Table[Any]]:
        return self.source

    def __compile_sql__(self, ctx: CompileCtx) -> tuple[str, tuple[object, ...]]:
        owner = ctx.quote_identifier(require_model_table_name(self.source))
        return f"{owner}.{ctx.quote_identifier(self.name)}", ()


def table_presence_name(source: type[Table[Any]]) -> str | None:
    """Only tables without a non-nullable column need an extra presence witness."""
    if issubclass(source, _CteRelation):
        return None
    columns = require_model_columns(source)
    if any(not column.nullable for column in columns.values()):
        return None
    names = {name.casefold() for name in columns}
    marker = "__snekql_present"
    while marker.casefold() in names:
        marker += "_"
    return marker


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
            for position in range(len(source.definition.layout.slots))
        )
        return (*outputs, _CtePresence(source)) if presence else outputs
    columns = tuple(require_model_columns(source).values())
    marker = table_presence_name(source) if presence else None
    return (*columns, _TablePresence(source, marker)) if marker is not None else columns


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
