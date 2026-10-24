"""Bounded named whole-column index additions, never implicit adoption."""

from snekql.errors import SchemaError
from snekql.experimental._migration_sql import ascii_lower, tokens
from snekql.experimental.migrations import Backend, PackageError, TableState


def _parse_index_name(sql: str, table: TableState, backend: Backend) -> str:
    """Accept only unconditional compiler-shaped CREATE [UNIQUE] INDEX declarations."""
    stream = tokens(sql, mysql=backend == "mariadb")
    end = 0
    for token in stream:
        if sql[end : token.start].strip():
            msg = "comments require an explicit adapter"
            raise ValueError(msg)
        end = token.end
    if sql[end:].strip():
        msg = "comments require an explicit adapter"
        raise ValueError(msg)
    offset = int((stream[1].kind, ascii_lower(stream[1].value)) == ("word", "unique"))
    words = tuple((t.kind, ascii_lower(t.value)) for t in stream)
    if (
        words[0] != ("word", "create")
        or words[1 + offset] != ("word", "index")
        or words[3 + offset] != ("word", "on")
    ):
        msg = "expected unconditional CREATE INDEX"
        raise ValueError(msg)
    name, owner = stream[2 + offset], stream[4 + offset]
    if (
        name.kind != "identifier"
        or not name.value
        or owner.kind != "identifier"
        or owner.value != table.name
    ):
        msg = "index name or owner differs"
        raise ValueError(msg)
    if words[5 + offset] != ("punct", "(") or words[-1] != ("punct", ")"):
        msg = "expected whole-column index members"
        raise ValueError(msg)
    members = stream[6 + offset : -1]
    columns = {column.name for column in table.columns}
    if (
        not members
        or len(members) % 2 != 1
        or any(
            (token.kind != "identifier" or token.value not in columns)
            if index % 2 == 0
            else (token.kind, token.value) != ("punct", ",")
            for index, token in enumerate(members)
        )
    ):
        msg = "unsupported index members, predicate or options"
        raise ValueError(msg)
    return name.value


def _index_name(sql: str, table: TableState, backend: Backend) -> str:
    try:
        return _parse_index_name(sql, table, backend)
    except (SchemaError, IndexError, ValueError) as error:
        msg = f"unsupported index addition: {error}; explicit adapter required"
        raise PackageError(msg) from error


def add_index(table: TableState, sql: str, backend: Backend) -> TableState:
    """Append a distinct declared index; execution must create it rather than adopt it."""
    name = _index_name(sql, table, backend)
    names = {_index_name(existing, table, backend) for existing in table.indexes}
    if ascii_lower(name) in {ascii_lower(existing) for existing in names}:
        msg = "index addition requires a new managed index name"
        raise PackageError(msg)
    return table.model_copy(update={"indexes": (*table.indexes, sql)})
