"""Bounded native schema-fact comparison for recorded migration contracts."""

import re
from dataclasses import dataclass

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
_JSON_CHECK_TOKENS = 4
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
            mariadb_table_engine(table.sql)
            mariadb_declared_indexes(table)
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


def mariadb_declared_json_columns(table: TableState) -> tuple[str, ...]:
    """Identify JSON aliases in already validated recorded type prefixes."""
    names: list[str] = []
    for column in table.columns:
        declaration = _COLUMN.match(column.definition)
        datatype = _TYPE.match(str(declaration[1])) if declaration is not None else None
        if datatype is not None and str(datatype[1]).lower() == "json":
            names.append(column.name)
    return tuple(names)


def _check_expression(stream: tuple[Token, ...]) -> tuple[Token, ...]:
    """Take one balanced CHECK expression, excluding its outer parentheses."""
    if not stream or (stream[0].kind, stream[0].value) != ("punct", "("):
        return ()
    depth = 0
    for index, token in enumerate(stream):
        if token.kind == "punct" and token.value == "(":
            depth += 1
        elif token.kind == "punct" and token.value == ")":
            depth -= 1
            if depth == 0:
                return stream[1:index]
    return ()


def _json_check_reference(expression: tuple[Token, ...]) -> str | None:
    """Recognize only JSON_VALID(quoted-column), never constants or weaker checks."""
    while expression and (expression[0].kind, expression[0].value) == ("punct", "("):
        inner = _check_expression(expression)
        if len(inner) != len(expression) - 2:
            break
        expression = inner
    if len(expression) != _JSON_CHECK_TOKENS:
        return None
    function, opening, argument, closing = expression
    if (
        (function.kind, function.value.lower()) == ("word", "json_valid")
        and (opening.kind, opening.value) == ("punct", "(")
        and argument.kind == "identifier"
        and (closing.kind, closing.value) == ("punct", ")")
    ):
        return argument.value
    return None


def mariadb_json_check_columns(sql: str, *, backslash_escapes: bool) -> tuple[str, ...]:
    """Extract recognized native CHECK references, not evidence from arbitrary SQL text."""
    names: list[str] = []
    try:
        _, parts, _ = split_table(sql, mysql=backslash_escapes)
        for part in parts:
            stream = tokens(part, mysql=backslash_escapes)
            depth = 0
            for index, token in enumerate(stream):
                if token.kind == "punct" and token.value == "(":
                    depth += 1
                elif token.kind == "punct" and token.value == ")":
                    depth -= 1
                elif depth == 0 and (token.kind, token.value.lower()) == (
                    "word",
                    "check",
                ):
                    reference = _json_check_reference(
                        _check_expression(stream[index + 1 :])
                    )
                    if reference is not None:
                        names.append(reference)
    except SchemaError:
        return ()  # Unsupported rendering is no proof of a required JSON check.
    return tuple(names)


def _engine_option(stream: tuple[Token, ...], index: int) -> tuple[str, int]:
    """Read a single literal engine option, not a session variable or expression."""
    if index < len(stream) and stream[index].value == "=":
        index += 1
    if index >= len(stream):
        msg = "unsupported MariaDB engine declaration; explicit adapter required"
        raise PackageError(msg)
    token = stream[index]
    if (
        token.kind not in {"word", "identifier", "string"}
        or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", token.value) is None
    ):
        msg = "unsupported MariaDB engine declaration; explicit adapter required"
        raise PackageError(msg)
    name = token.value.lower()
    if name == "default":
        msg = (
            "unsupported MariaDB DEFAULT engine declaration; explicit adapter required"
        )
        raise PackageError(msg)
    return {"heap": "memory", "merge": "mrg_myisam"}.get(name, name), index + 1


def mariadb_table_engine(sql: str, *, backslash_escapes: bool = True) -> str | None:
    """Read an explicit table engine; an absent option makes no fixed claim."""
    try:
        head = [
            (token.kind, token.value.lower())
            for token in tokens(sql, mysql=backslash_escapes)[:5]
        ]
        if head[:1] != [("word", "create")]:
            return None
        position = 3 if head[1:3] == [("word", "or"), ("word", "replace")] else 1
        if head[position : position + 1] == [("word", "temporary")]:
            position += 1
        if head[position : position + 1] != [("word", "table")]:
            return None
        _, _, suffix = split_table(sql, mysql=backslash_escapes)
        stream = tokens(suffix, mysql=backslash_escapes)
    except SchemaError as error:
        raise PackageError(str(error)) from error
    options: list[str] = []
    depth = 0
    index = 0
    while index < len(stream):
        token = stream[index]
        index += 1
        if token.kind == "punct" and token.value == "(":
            depth += 1
        elif token.kind == "punct" and token.value == ")":
            depth -= 1
        elif depth == 0 and (token.kind, token.value.lower()) == ("word", "engine"):
            value, index = _engine_option(stream, index)
            options.append(value)
    if len(options) > 1:
        msg = "multiple MariaDB engine declarations require an explicit adapter"
        raise PackageError(msg)
    return options[0] if options else None


def mariadb_engine_obstacle(
    table: TableState, observed: str, *, backslash_escapes: bool
) -> str | None:
    """Compare the explicit recorded engine to the already server-resolved definition."""
    expected = mariadb_table_engine(table.sql)
    if expected is None:
        return None
    try:
        actual = mariadb_table_engine(observed, backslash_escapes=backslash_escapes)
    except PackageError as error:
        return f"managed table postcondition failed: {table.name!r} has unsupported engine metadata: {error}; committed MariaDB effects may remain"
    if expected != actual:
        return f"managed table postcondition failed: {table.name!r} engine differs from the recorded contract or is unavailable in metadata; committed MariaDB effects may remain"
    return None


@dataclass(frozen=True)
class MariaDBIndex:
    """A bounded recorded secondary-index claim, not a serialized artifact field."""

    name: str
    columns: tuple[str, ...]
    unique: bool
    prefixes: tuple[int | None, ...]


def _index_member(part: tuple[Token, ...]) -> tuple[str, int | None]:
    """Read one ascending column, with an optional positive literal prefix."""
    if len(part) > 1 and (part[-1].kind, part[-1].value.lower()) == ("word", "asc"):
        part = part[:-1]
    if not part or part[0].kind not in {"word", "identifier"}:
        msg = "unsupported MariaDB secondary index member"
        raise PackageError(msg)
    if len(part) == 1:
        return part[0].value, None
    opening, count, closing = part[1:]
    if (
        (opening.kind, opening.value) != ("punct", "(")
        or (closing.kind, closing.value) != ("punct", ")")
        or count.kind != "word"
        or re.fullmatch(r"[1-9][0-9]*", count.value) is None
    ):
        msg = "unsupported MariaDB secondary index prefix"
        raise PackageError(msg)
    return part[0].value, int(count.value)


def _index_members(stream: tuple[Token, ...]) -> tuple[tuple[str, int | None], ...]:
    """Split a bounded key list without treating prefix parentheses as members."""
    body = _check_expression(stream)
    if not body or len(body) != len(stream) - 2:
        msg = "unsupported MariaDB secondary index key list or options"
        raise PackageError(msg)
    start = 0
    depth = 0
    parts: list[tuple[Token, ...]] = []
    for index, token in enumerate(body):
        if token.kind == "punct" and token.value == "(":
            depth += 1
        elif token.kind == "punct" and token.value == ")":
            depth -= 1
        elif token.kind == "punct" and token.value == "," and depth == 0:
            parts.append(body[start:index])
            start = index + 1
    parts.append(body[start:])
    return tuple(_index_member(part) for part in parts)


def _secondary_index(sql: str, table: str) -> MariaDBIndex:
    """Read emitted CREATE [UNIQUE] INDEX, optionally guarded by IF NOT EXISTS."""
    stream = tokens(sql, mysql=True)
    words = tuple(
        token.value.lower() if token.kind == "word" else None for token in stream
    )
    position = 1
    unique = words[1:2] == ("unique",)
    position += int(unique)
    if words[:1] != ("create",) or words[position : position + 1] != ("index",):
        msg = (
            "unsupported MariaDB secondary index declaration; explicit adapter required"
        )
        raise PackageError(msg)
    position += 1
    if words[position : position + 3] == ("if", "not", "exists"):
        position += 3
    name, on, owner = stream[position : position + 3]
    if (
        name.kind not in {"word", "identifier"}
        or name.value.lower() == "primary"
        or (on.kind, on.value.lower()) != ("word", "on")
        or owner.kind not in {"word", "identifier"}
        or owner.value != table
    ):
        msg = "unsupported MariaDB secondary index name or owner; explicit adapter required"
        raise PackageError(msg)
    members = _index_members(stream[position + 3 :])
    return MariaDBIndex(
        name=name.value,
        columns=tuple(column for column, _ in members),
        unique=unique,
        prefixes=tuple(prefix for _, prefix in members),
    )


def mariadb_declared_indexes(table: TableState) -> tuple[MariaDBIndex, ...]:
    """Require bounded declarations before executing native index construction."""
    try:
        indexes = tuple(_secondary_index(sql, table.name) for sql in table.indexes)
    except (SchemaError, ValueError) as error:
        msg = f"unsupported MariaDB secondary index declaration: {error}"
        raise PackageError(msg) from error
    if len({index.name for index in indexes}) != len(indexes):
        msg = "duplicate MariaDB secondary index claims require an explicit adapter"
        raise PackageError(msg)
    return indexes
