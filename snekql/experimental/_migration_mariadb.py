"""Bounded native schema-fact comparison for recorded migration contracts."""

import re

from snekql.errors import SchemaError
from snekql.experimental._migration_sql import Token, split_table, tokens
from snekql.experimental.migrations import PackageError, State, TableState

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
_KEY_LIST_MIN_TOKENS = 3
_INTEGERS = {"tinyint", "smallint", "mediumint", "int", "bigint"}
_ALIASES = {
    "integer": "int",
    "bool": "tinyint",
    "boolean": "tinyint",
    "numeric": "decimal",
    "dec": "decimal",
    "fixed": "decimal",
    "double precision": "double",
    # JSON validity and collation are separate from storage-type proof.
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
                mariadb_declared_collation(column.definition)
                mariadb_declared_auto_increment(column.definition)
            except PackageError as error:
                return f"{table.name!r}.{column.name!r}: {error}"
        try:
            mariadb_declared_primary_key(table)
        except PackageError as error:
            return f"{table.name!r}: {error}"
    return None


def validate_mariadb_declarations(state: State) -> None:
    """Fail preflight for unsupported native declarations; leave SQLite untouched."""
    if state.backend == "mariadb" and (obstacle := mariadb_declaration_obstacle(state)):
        raise PackageError(obstacle)


def mariadb_declared_collation(definition: str) -> str | None:
    """Read an explicit supported type-prefix collation, not default/expression text."""
    column = _COLUMN.match(definition)
    if column is None:
        msg = "unsupported MariaDB column declaration; explicit adapter required"
        raise PackageError(msg)
    source = str(column[1])
    datatype = _TYPE.match(source)
    if datatype is None:
        msg = "unsupported MariaDB storage type syntax; explicit adapter required"
        raise PackageError(msg)
    tail = source[datatype.end() :].strip()
    charset = re.match(
        r"character\s+set\s+utf8mb4(?=\s|$)", tail, re.IGNORECASE | re.ASCII
    )
    if charset is not None:
        tail = tail[charset.end() :].strip()
    collation = re.match(
        r"collate\s+(utf8mb4_[a-z0-9_]+)(?=\s|$)", tail, re.IGNORECASE | re.ASCII
    )
    remainder = tail[collation.end() :] if collation is not None else tail
    try:
        stream = tokens(remainder, mysql=True)
    except SchemaError as error:
        raise PackageError(str(error)) from error
    if any(
        token.kind == "word" and token.value.lower() == "collate" for token in stream
    ):
        msg = "unsupported MariaDB collation position; explicit adapter required"
        raise PackageError(msg)
    if collation is not None:
        return str(collation[1]).lower()
    return "utf8mb4_bin" if str(datatype[1]).lower() == "json" else None


def mariadb_declared_auto_increment(definition: str) -> bool:
    """Recognize a bounded attribute prefix, never reinterpret arbitrary defaults."""
    column = _COLUMN.match(definition)
    source = str(column[1]) if column is not None else ""
    datatype = _TYPE.match(source)
    if datatype is None:
        msg = "unsupported MariaDB storage type syntax; explicit adapter required"
        raise PackageError(msg)
    try:
        stream = tokens(source[datatype.end() :], mysql=True)
    except SchemaError as error:
        raise PackageError(str(error)) from error
    depth = 0
    unparsed = False
    found = False
    prefix_words = {"not", "null", "primary", "key", "unique", "invisible", "visible"}
    for token in stream:
        if token.kind == "punct" and token.value == "(":
            depth += 1
        elif token.kind == "punct" and token.value == ")":
            depth -= 1
        elif depth == 0 and token.kind == "word":
            word = token.value.lower()
            if word == "auto_increment":
                if unparsed:
                    msg = "unsupported MariaDB AUTO_INCREMENT position; explicit adapter required"
                    raise PackageError(msg)
                found = True
            elif word not in prefix_words:
                unparsed = True
    return found


def _inline_primary_key(definition: str) -> bool:
    """Read an inline primary-key attribute without treating literals as syntax."""
    column = _COLUMN.match(definition)
    source = str(column[1]) if column is not None else ""
    datatype = _TYPE.match(source)
    if datatype is None:
        msg = "unsupported MariaDB storage type syntax; explicit adapter required"
        raise PackageError(msg)
    tail = source[datatype.end() :].strip()
    tail = re.sub(
        r"^(?:character\s+set\s+utf8mb4\s+)?(?:collate\s+utf8mb4_[a-z0-9_]+\s+)?",
        "",
        tail,
        flags=re.IGNORECASE | re.ASCII,
    )
    stream = tokens(tail, mysql=True)
    depth = 0
    unparsed = False
    found = False
    prefix_words = {
        "not",
        "null",
        "primary",
        "key",
        "unique",
        "auto_increment",
        "visible",
        "invisible",
    }
    for index, token in enumerate(stream):
        if token.kind == "punct" and token.value == "(":
            depth += 1
        elif token.kind == "punct" and token.value == ")":
            depth -= 1
        elif depth == 0 and token.kind == "word":
            word = token.value.lower()
            if word == "primary" and [
                (t.kind, t.value.lower()) for t in stream[index + 1 : index + 2]
            ] == [("word", "key")]:
                if unparsed:
                    msg = "unsupported MariaDB primary-key position; explicit adapter required"
                    raise PackageError(msg)
                found = True
            elif word not in prefix_words:
                unparsed = True
    return found


def _primary_key_members(stream: tuple[Token, ...]) -> tuple[str, ...]:
    """Accept only an ordered list of full columns with implicit/explicit ASC."""
    if (
        len(stream) < _KEY_LIST_MIN_TOKENS
        or (stream[0].kind, stream[0].value) != ("punct", "(")
        or (stream[-1].kind, stream[-1].value) != ("punct", ")")
    ):
        msg = "unsupported MariaDB primary-key definition; explicit adapter required"
        raise PackageError(msg)
    members: list[str] = []
    index = 1
    while index < len(stream) - 1:
        token = stream[index]
        if token.kind not in {"word", "identifier"}:
            msg = "unsupported MariaDB primary-key member; explicit adapter required"
            raise PackageError(msg)
        members.append(token.value)
        index += 1
        if stream[index].kind == "word" and stream[index].value.lower() == "asc":
            index += 1
        if index == len(stream) - 1:
            break
        if stream[index].value != "," or index + 1 == len(stream) - 1:
            msg = "unsupported MariaDB primary-key suffix; explicit adapter required"
            raise PackageError(msg)
        index += 1
    return tuple(members)


def _table_primary_keys(sql: str) -> tuple[tuple[str, ...], ...]:
    """Read only table-level PRIMARY KEY declarations from ordinary CREATE TABLE."""
    head = tokens(sql, mysql=True)[:2]
    if [(token.kind, token.value.lower()) for token in head] != [
        ("word", "create"),
        ("word", "table"),
    ]:
        return ()  # Other trusted construction is still subject to endpoint checks.
    _, parts, _ = split_table(sql, mysql=True)
    keys: list[tuple[str, ...]] = []
    for part in parts:
        stream = tokens(part, mysql=True)
        if not stream:
            msg = "unsupported empty MariaDB table definition"
            raise PackageError(msg)
        if stream[0].kind == "word" and stream[0].value.lower() == "constraint":
            stream = stream[1:]
            if stream and (stream[0].kind, stream[0].value.lower()) != (
                "word",
                "primary",
            ):
                stream = stream[1:]
        if stream and stream[0].kind == "word" and stream[0].value.lower() == "primary":
            if [(token.kind, token.value.lower()) for token in stream[:2]] != [
                ("word", "primary"),
                ("word", "key"),
            ]:
                msg = "unsupported MariaDB primary-key declaration; explicit adapter required"
                raise PackageError(msg)
            keys.append(_primary_key_members(stream[2:]))
    return tuple(keys)


def mariadb_declared_primary_key(table: TableState) -> tuple[str, ...]:
    """Combine inline column claims and bounded table-level key declarations."""
    try:
        inline = tuple(
            column.name
            for column in table.columns
            if _inline_primary_key(column.definition)
        )
        keys = _table_primary_keys(table.sql)
    except SchemaError as error:
        raise PackageError(str(error)) from error
    if len(inline) > 1 or len(keys) > 1 or (inline and keys):
        msg = "multiple primary-key declarations require an explicit MariaDB adapter"
        raise PackageError(msg)
    return inline or (keys[0] if keys else ())
