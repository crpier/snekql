"""Bounded native storage-type comparison for recorded migration contracts."""

import re

from snekql.experimental.migrations import PackageError, State

_COLUMN = re.compile(
    r'^\s*(?:`(?:``|[^`])*`|"(?:""|[^"])*"|[^\s`"]+)\s+(.*)$', re.DOTALL
)
_TYPE = re.compile(
    r"^\s*(double\s+precision|[a-z]+)"
    r"(?:\s*\(\s*([0-9]+(?:\s*,\s*[0-9]+)*)\s*\))?"
    r"(?:\s+(unsigned|signed))?(?=\s|$)",
    re.IGNORECASE | re.ASCII,
)
_DECIMAL_ARITY = 2
_INTEGERS = {"tinyint", "smallint", "mediumint", "int", "bigint"}
_ALIASES = {
    "integer": "int",
    "bool": "tinyint",
    "boolean": "tinyint",
    "numeric": "decimal",
    "dec": "decimal",
    "fixed": "decimal",
    "double precision": "double",
    # JSON validity and collation are separate constraints, not storage-type proof.
    "json": "longtext",
}
_PLAIN = {
    "date",
    "uuid",
    "float",
    "double",
    "tinytext",
    "text",
    "mediumtext",
    "longtext",
    "tinyblob",
    "blob",
    "mediumblob",
    "longblob",
}
_ATTRIBUTES = {
    "not",
    "null",
    "primary",
    "unique",
    "auto_increment",
    "default",
    "check",
    "references",
    "comment",
    "generated",
    "as",
    "invisible",
    "visible",
}


def _parameters(family: str, parameters: tuple[int, ...]) -> tuple[int, ...]:
    """Normalize only understood parameters, retaining meaningful sizes and precision."""
    if family in _INTEGERS and len(parameters) <= 1:
        return ()  # Integer display widths do not change the non-ZEROFILL domain.
    if family in {"char", "binary", "bit"} and len(parameters) <= 1:
        return parameters or (1,)
    if family in {"varchar", "varbinary"} and len(parameters) == 1:
        return parameters
    if family in {"datetime", "timestamp", "time"} and len(parameters) <= 1:
        return parameters or (0,)
    if family == "decimal" and len(parameters) <= _DECIMAL_ARITY:
        return (
            (parameters[0], parameters[1] if len(parameters) == _DECIMAL_ARITY else 0)
            if parameters
            else (10, 0)
        )
    if family in _PLAIN and not parameters:
        return ()
    msg = "unsupported MariaDB storage type or parameters; explicit adapter required"
    raise PackageError(msg)


def _supported_tail(tail: str, *, declaration: bool) -> bool:
    """Bound modifier syntax without interpreting defaults or arbitrary SQL."""
    if not tail:
        return True
    if not declaration:
        return False
    for keyword, pattern in (
        ("character", r"character\s+set\s+utf8mb4(?=\s|$)"),
        ("collate", r"collate\s+utf8mb4_[a-z0-9_]+(?=\s|$)"),
    ):
        if tail.split(maxsplit=1)[0].lower() == keyword:
            match = re.match(pattern, tail, re.IGNORECASE | re.ASCII)
            if match is None:
                return False
            tail = tail[match.end() :].strip()
            if not tail:
                return True
    return tail.split()[0].lower() in _ATTRIBUTES


def _signature(source: str, *, declaration: bool) -> tuple[str, tuple[int, ...], bool]:
    """Parse a type prefix without scanning unrelated defaults or constraints."""
    if declaration:
        column = _COLUMN.match(source)
        if column is None:
            msg = "unsupported MariaDB column declaration; explicit adapter required"
            raise PackageError(msg)
        source = str(column[1])
    match = _TYPE.match(source)
    if match is None:
        msg = "unsupported MariaDB storage type syntax; explicit adapter required"
        raise PackageError(msg)
    family = " ".join(str(match[1]).lower().split())
    family = _ALIASES.get(family, family)
    parameters = (
        tuple(int(item.strip()) for item in str(match[2]).split(","))
        if match[2]
        else ()
    )
    tail = source[match.end() :].strip()
    if not _supported_tail(tail, declaration=declaration):
        msg = "unsupported MariaDB type modifier; explicit adapter required"
        raise PackageError(msg)
    unsigned = match[3] is not None and str(match[3]).lower() == "unsigned"
    if unsigned and family not in _INTEGERS | {"decimal", "float", "double"}:
        msg = "unsupported MariaDB unsigned type; explicit adapter required"
        raise PackageError(msg)
    return family, _parameters(family, parameters), unsigned


def mariadb_storage_type_matches(definition: str, observed: str) -> bool:
    """Compare frozen declared storage with native type metadata, not codec semantics."""
    return _signature(definition, declaration=True) == _signature(
        observed, declaration=False
    )


def mariadb_declaration_obstacle(state: State) -> str | None:
    """Reject unsupported recorded types before committing native construction SQL."""
    for table in state.tables:
        for column in table.columns:
            try:
                _signature(column.definition, declaration=True)
            except PackageError as error:
                return f"{table.name!r}.{column.name!r}: {error}"
    return None


def validate_mariadb_declarations(state: State) -> None:
    """Fail preflight for unsupported native declarations; leave SQLite untouched."""
    if state.backend == "mariadb" and (obstacle := mariadb_declaration_obstacle(state)):
        raise PackageError(obstacle)
