"""Bounded native schema-fact comparison for recorded migration contracts."""

import re
from collections import Counter
from dataclasses import dataclass

from snekql._check_catalog import normalize_check, parse_check, parse_default_literal
from snekql._checks import CheckExpression
from snekql.errors import SchemaError
from snekql.experimental._migration_sql import Token, column_name, split_table, tokens
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
_EMPTY_ARGUMENT_TOKENS = 2
_CHECK_TOKEN_LIMIT = 4096
_CHECK_PAREN_LIMIT = 32
_CHECK_TREE_LIMIT = 64
_CHECK_WORK_LIMIT = 4096
_CONSTRAINT_PREFIX_TOKENS = 2
_SINGLE_MEMBERSHIP_ARITY = 2
_PRECISION_ARGUMENT_TOKENS = 3
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
    "on",
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


def mariadb_construction_storage_matches(definition: str, constructed: str) -> bool:
    """Compare only supported declaration domains, parameters, aliases and signedness."""
    return _signature(definition, declaration=True) == _signature(
        constructed, declaration=True
    )


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
                mariadb_declared_generation(column.definition)
                mariadb_declared_invisible(column.definition)
                mariadb_declared_on_update(column.definition)
                mariadb_declared_default(column.definition)
                if (
                    mariadb_declared_null_default(column.definition)
                    and not column.nullable
                ):
                    return f"{table.name!r}.{column.name!r}: MariaDB DEFAULT NULL requires a nullable recorded column; explicit adapter required"
            except PackageError as error:
                return f"{table.name!r}.{column.name!r}: {error}"
        try:
            mariadb_declared_primary_key(table)
            mariadb_table_engine(table.sql)
            mariadb_declared_indexes(table)
            mariadb_declared_foreign_keys(table)
            _validate_check_claims(table)
        except (PackageError, SchemaError) as error:
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
                _check_auto_increment_position(found=found, unparsed=unparsed)
                found = True
            elif word not in prefix_words:
                unparsed = True
    return found


def _check_auto_increment_position(*, found: bool, unparsed: bool) -> None:
    """Require one generator attribute within the supported declaration prefix."""
    if found:
        msg = "multiple MariaDB AUTO_INCREMENT clauses require an explicit adapter"
        raise PackageError(msg)
    if unparsed:
        msg = "unsupported MariaDB AUTO_INCREMENT position; explicit adapter required"
        raise PackageError(msg)


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


def _generation_words(stream: tuple[Token, ...]) -> tuple[str, ...]:
    """Find attribute words without interpreting quoted names/literals or expressions."""
    depth = 0
    result: list[str] = []
    for token in stream:
        if token.kind == "punct" and token.value == "(":
            depth += 1
        elif token.kind == "punct" and token.value == ")":
            depth -= 1
        elif (
            depth == 0
            and token.kind == "word"
            and token.value.lower()
            in {"as", "generated", "always", "virtual", "stored", "persistent"}
        ):
            result.append(token.value.lower())
    return tuple(result)


def mariadb_declared_generation(definition: str) -> str:
    """Classify a bounded AS(expression) clause, without proving its expression."""
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
    try:
        stream = tokens(tail, mysql=True)
    except SchemaError as error:
        raise PackageError(str(error)) from error
    if not _generation_words(stream):
        return "ordinary"
    words = tuple(
        token.value.lower() if token.kind == "word" else None for token in stream
    )
    position = 2 if words[:2] == ("generated", "always") else 0
    expression = _check_expression(stream[position + 1 :])
    if words[position : position + 1] != ("as",) or not expression:
        msg = (
            "unsupported MariaDB generation clause position; explicit adapter required"
        )
        raise PackageError(msg)
    remainder = stream[position + len(expression) + 3 :]
    kind = "virtual"
    if (
        remainder
        and remainder[0].kind == "word"
        and remainder[0].value.lower() in {"virtual", "stored", "persistent"}
    ):
        kind = "virtual" if remainder[0].value.lower() == "virtual" else "stored"
        remainder = remainder[1:]
    if _generation_words(remainder):
        msg = "unsupported MariaDB generation clause suffix; explicit adapter required"
        raise PackageError(msg)
    return kind


def mariadb_observed_generation(extra: str) -> str:
    """Read native generation flags separately from defaults and other EXTRA facts."""
    words = mariadb_extra_words(extra)
    flags = words & {"VIRTUAL", "STORED", "PERSISTENT", "GENERATED"}
    if flags == {"VIRTUAL", "GENERATED"}:
        return "virtual"
    if flags == {"STORED", "GENERATED"}:
        return "stored"
    if not flags:
        return "ordinary"
    msg = "unsupported MariaDB generation metadata; explicit adapter required"
    raise PackageError(msg)


def mariadb_declared_invisible(definition: str) -> bool:
    """Recognize bounded visibility attributes without guessing unparsed SQL roles."""
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
    try:
        stream = tokens(tail, mysql=True)
    except SchemaError as error:
        raise PackageError(str(error)) from error
    return _invisible_attribute(stream)


def _invisible_attribute(stream: tuple[Token, ...]) -> bool:
    """Keep literal/expression roles separate from visibility attribute markers."""
    position = 0
    literal = False
    unparsed = False
    found = False
    attributes = {
        "not",
        "null",
        "primary",
        "key",
        "unique",
        "auto_increment",
        "generated",
        "always",
        "as",
        "virtual",
        "stored",
        "persistent",
        "check",
    }
    while position < len(stream):
        token = stream[position]
        position += 1
        if (token.kind, token.value) == ("punct", "("):
            expression = _check_expression(stream[position - 1 :])
            if not expression:
                unparsed = True
            position += len(expression) + 1
            literal = False
            continue
        word = token.value.lower() if token.kind == "word" else None
        if word in {"visible", "invisible"}:
            if word == "visible" or literal or unparsed or found:
                msg = "unsupported MariaDB visibility attribute position or declaration; explicit adapter required"
                raise PackageError(msg)
            found = True
        elif literal:
            if (
                token.kind != "string"
                and word not in {"null", "true", "false"}
                and (word is None or re.fullmatch(r"[0-9]+", word) is None)
            ):
                unparsed = True
            literal = False
        elif word in {"default", "comment"}:
            literal = True
        elif word not in attributes:
            unparsed = True
    return found


def mariadb_extra_words(extra: str) -> frozenset[str]:
    """Separate native comma-delimited EXTRA attributes without losing flag words."""
    return frozenset(extra.replace(",", " ").upper().split())


def _on_update_prefix(stream: tuple[Token, ...]) -> bool:
    """Accept bounded attributes/default roles before an automatic-update clause."""
    position = 0
    literal = False
    while position < len(stream):
        token = stream[position]
        position += 1
        if (token.kind, token.value) == ("punct", "("):
            expression = _check_expression(stream[position - 1 :])
            position += len(expression) + 1
            literal = False
            continue
        word = token.value.lower() if token.kind == "word" else None
        if literal:
            if (
                token.kind != "string"
                and word not in {"null", "current_timestamp", "true", "false"}
                and (word is None or re.fullmatch(r"[0-9]+", word) is None)
            ):
                return False
            literal = False
        elif word in {"default", "comment"}:
            literal = True
        elif word not in {"null", "not", "primary", "key", "unique", "invisible"}:
            return False
    return not literal


def mariadb_declared_on_update(definition: str) -> int | None:
    """Read CURRENT_TIMESTAMP update precision; do not certify default values."""
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
    positions: list[int] = []
    depth = 0
    for index, token in enumerate(stream):
        if (token.kind, token.value) == ("punct", "("):
            depth += 1
        elif (token.kind, token.value) == ("punct", ")"):
            depth -= 1
        elif depth == 0 and (token.kind, token.value.lower()) == ("word", "on"):
            positions.append(index)
    if not positions:
        return None
    if (
        len(positions) != 1
        or str(datatype[1]).lower() not in {"datetime", "timestamp"}
        or not _on_update_prefix(stream[: positions[0]])
    ):
        msg = "unsupported MariaDB ON UPDATE position; explicit adapter required"
        raise PackageError(msg)
    position = positions[0]
    clause = stream[position:]
    words = tuple(
        token.value.lower() if token.kind == "word" else None for token in clause
    )
    if words[:3] != ("on", "update", "current_timestamp"):
        msg = "unsupported MariaDB ON UPDATE expression; explicit adapter required"
        raise PackageError(msg)
    precision = int(str(datatype[2])) if datatype[2] is not None else 0
    _validate_on_update_suffix(clause[3:], precision)
    return precision


def _validate_on_update_suffix(remainder: tuple[Token, ...], precision: int) -> None:
    """Normalize omitted precision and reject conflicting or unknown suffixes."""
    if remainder and (remainder[0].kind, remainder[0].value) == ("punct", "("):
        # An empty argument list uses the column precision, just like no list.
        if len(remainder) >= _EMPTY_ARGUMENT_TOKENS and (
            remainder[1].kind,
            remainder[1].value,
        ) == (
            "punct",
            ")",
        ):
            remainder = remainder[2:]
        elif (
            len(remainder) >= _PRECISION_ARGUMENT_TOKENS
            and remainder[1].kind == "word"
            and re.fullmatch(r"[0-6]", remainder[1].value)
            and (remainder[2].kind, remainder[2].value) == ("punct", ")")
        ):
            if int(remainder[1].value) != precision:
                msg = "MariaDB ON UPDATE precision must match the column; explicit adapter required"
                raise PackageError(msg)
            remainder = remainder[3:]
        else:
            msg = "unsupported MariaDB ON UPDATE precision; explicit adapter required"
            raise PackageError(msg)
    if not _on_update_prefix(remainder):
        msg = "unsupported MariaDB ON UPDATE suffix; explicit adapter required"
        raise PackageError(msg)


def mariadb_observed_on_update(extra: str) -> int | None:
    """Read the canonical native EXTRA clause without conflating other attributes."""
    clauses = [
        part.strip()
        for part in extra.split(",")
        if re.search(r"\b(?:on|update)\b", part, re.IGNORECASE | re.ASCII)
    ]
    if not clauses:
        return None
    match = re.fullmatch(
        r"on\s+update\s+current_timestamp(?:\(([0-6]?)\))?",
        clauses[0],
        re.IGNORECASE | re.ASCII,
    )
    if len(clauses) != 1 or match is None:
        msg = "unsupported MariaDB ON UPDATE metadata; explicit adapter required"
        raise PackageError(msg)
    return int(match[1] or "0")


@dataclass(frozen=True)
class _ForeignKey:
    """Ordered relationship identity; constraint names and enforcement are separate."""

    columns: tuple[str, ...]
    target: str
    references: tuple[str, ...]
    on_delete: str
    on_update: str


def _foreign_key_members(
    stream: tuple[Token, ...],
) -> tuple[tuple[str, ...], tuple[Token, ...]]:
    """Read full identifier members, not expressions, ordering or prefix lengths."""
    body = _check_expression(stream)
    if (
        not body
        or len(body) % 2 == 0
        or any(token.kind not in {"word", "identifier"} for token in body[::2])
        or any((token.kind, token.value) != ("punct", ",") for token in body[1::2])
    ):
        msg = "unsupported MariaDB foreign-key members; explicit adapter required"
        raise PackageError(msg)
    return tuple(token.value for token in body[::2]), stream[len(body) + 2 :]


def _foreign_reference(
    columns: tuple[str, ...], stream: tuple[Token, ...]
) -> _ForeignKey:
    """Read unqualified references and bounded immediate referential actions."""
    if not stream or stream[0].kind not in {"word", "identifier"}:
        msg = "unsupported MariaDB foreign-key target; explicit adapter required"
        raise PackageError(msg)
    target = stream[0].value
    references, remainder = _foreign_key_members(stream[1:])
    if len(columns) != len(references):
        msg = "MariaDB foreign-key member counts differ"
        raise PackageError(msg)
    actions: dict[str, str] = {}
    words = tuple(
        token.value.lower() if token.kind == "word" else None for token in remainder
    )
    position = 0
    while position < len(words):
        prefix = words[position : position + 2]
        if (
            prefix not in {("on", "delete"), ("on", "update")}
            or str(prefix[1]) in actions
        ):
            msg = "unsupported MariaDB foreign-key action position; explicit adapter required"
            raise PackageError(msg)
        action = words[position + 2 : position + 3]
        if action in {("restrict",), ("cascade",)}:
            value = str(action[0])
            size = 3
        elif words[position + 2 : position + 4] in {("no", "action"), ("set", "null")}:
            value = "restrict" if words[position + 2] == "no" else "set null"
            size = 4
        else:
            msg = "unsupported MariaDB foreign-key action; explicit adapter required"
            raise PackageError(msg)
        actions[str(prefix[1])] = value
        position += size
    return _ForeignKey(
        columns,
        target,
        references,
        actions.get("delete", "restrict"),
        actions.get("update", "restrict"),
    )


def _table_foreign_keys(
    sql: str, *, backslash_escapes: bool = True
) -> tuple[_ForeignKey, ...]:
    """Extract table-level foreign-key definitions from ordinary construction SQL."""
    head = tokens(sql, mysql=backslash_escapes)[:2]
    if [(token.kind, token.value.lower()) for token in head] != [
        ("word", "create"),
        ("word", "table"),
    ]:
        return ()
    _, parts, _ = split_table(sql, mysql=backslash_escapes)
    keys: list[_ForeignKey] = []
    for part in parts:
        stream = tokens(part, mysql=backslash_escapes)
        if stream and (stream[0].kind, stream[0].value.lower()) == (
            "word",
            "constraint",
        ):
            stream = stream[1:]
            if stream and (stream[0].kind, stream[0].value.lower()) != (
                "word",
                "foreign",
            ):
                stream = stream[1:]
        if not stream or (stream[0].kind, stream[0].value.lower()) != (
            "word",
            "foreign",
        ):
            continue
        if [(token.kind, token.value.lower()) for token in stream[:2]] != [
            ("word", "foreign"),
            ("word", "key"),
        ]:
            msg = "unsupported MariaDB foreign-key definition"
            raise PackageError(msg)
        stream = stream[2:]
        if stream and stream[0].kind in {"word", "identifier"}:
            stream = stream[
                1:
            ]  # Optional supporting-index name is not relationship identity.
        columns, stream = _foreign_key_members(stream)
        if not stream or (stream[0].kind, stream[0].value.lower()) != (
            "word",
            "references",
        ):
            msg = "unsupported MariaDB foreign-key reference"
            raise PackageError(msg)
        keys.append(_foreign_reference(columns, stream[1:]))
    return tuple(keys)


def _inline_foreign_keys(name: str, definition: str) -> tuple[_ForeignKey, ...]:
    """Read simple inline references from the recorded column, not construction text."""
    column = _COLUMN.match(definition)
    source = str(column[1]) if column is not None else ""
    datatype = _TYPE.match(source)
    if datatype is None:
        msg = "unsupported MariaDB foreign-key column declaration"
        raise PackageError(msg)
    stream = tokens(source[datatype.end() :], mysql=True)
    depth = 0
    positions: list[int] = []
    for index, token in enumerate(stream):
        if (token.kind, token.value) == ("punct", "("):
            depth += 1
        elif (token.kind, token.value) == ("punct", ")"):
            depth -= 1
        elif depth == 0 and (token.kind, token.value.lower()) == ("word", "references"):
            positions.append(index)
    if not positions:
        return ()
    if len(positions) != 1 or not _on_update_prefix(stream[: positions[0]]):
        msg = "unsupported MariaDB foreign-key reference position; explicit adapter required"
        raise PackageError(msg)
    return (_foreign_reference((name,), stream[positions[0] + 1 :]),)


def mariadb_declared_foreign_keys(table: TableState) -> tuple[_ForeignKey, ...]:
    """Validate bounded relationship claims before any construction effects."""
    try:
        return _table_foreign_keys(table.sql) + tuple(
            key
            for column in table.columns
            for key in _inline_foreign_keys(column.name, column.definition)
        )
    except SchemaError as error:
        raise PackageError(str(error)) from error


def mariadb_foreign_key_obstacle(
    table: TableState, observed: str, *, backslash_escapes: bool
) -> str | None:
    """Compare native relationship definitions and multiplicity, not session policy."""
    try:
        actual = _table_foreign_keys(observed, backslash_escapes=backslash_escapes)
    except (SchemaError, PackageError) as error:
        return f"managed table postcondition failed: {table.name!r} has unsupported foreign-key metadata: {error}; committed MariaDB effects may remain"
    if Counter(actual) != Counter(mariadb_declared_foreign_keys(table)):
        return f"managed table postcondition failed: {table.name!r} foreign-key definitions differ from the recorded contract; committed MariaDB effects may remain"
    return None


def mariadb_declared_null_default(definition: str) -> bool:
    """Identify explicit bare/parenthesized SQL NULL, not general default expressions."""
    column = _COLUMN.match(definition)
    source = str(column[1]) if column is not None else ""
    datatype = _TYPE.match(source)
    if datatype is None:
        msg = "unsupported MariaDB storage type syntax; explicit adapter required"
        raise PackageError(msg)
    tail = re.sub(
        r"^(?:character\s+set\s+utf8mb4\s+)?(?:collate\s+utf8mb4_[a-z0-9_]+\s+)?",
        "",
        source[datatype.end() :].strip(),
        flags=re.IGNORECASE | re.ASCII,
    )
    try:
        stream = tokens(tail, mysql=True)
    except SchemaError as error:
        raise PackageError(str(error)) from error
    depth = 0
    positions: list[int] = []
    for index, token in enumerate(stream):
        if (token.kind, token.value) == ("punct", "("):
            depth += 1
        elif (token.kind, token.value) == ("punct", ")"):
            depth -= 1
        elif depth == 0 and (token.kind, token.value.lower()) == ("word", "default"):
            positions.append(index)
    if not positions:
        return False
    if len(positions) != 1:
        msg = "unsupported multiple MariaDB DEFAULT declarations; explicit adapter required"
        raise PackageError(msg)
    position = positions[0]
    return _null_default_value(stream[:position], stream[position + 1 :])


def _null_default_value(prefix: tuple[Token, ...], stream: tuple[Token, ...]) -> bool:
    """Prove only a standalone NULL term in a bounded attribute position."""
    if not stream:
        msg = "unsupported empty MariaDB DEFAULT declaration"
        raise PackageError(msg)
    expression = stream[:1]
    remainder = stream[1:]
    if (stream[0].kind, stream[0].value) == ("punct", "("):
        expression = _check_expression(stream)
        remainder = stream[len(expression) + 2 :]
        while expression and (expression[0].kind, expression[0].value) == (
            "punct",
            "(",
        ):
            inner = _check_expression(expression)
            if len(inner) != len(expression) - 2:
                return False
            expression = inner
    if [(token.kind, token.value.lower()) for token in expression] != [
        ("word", "null")
    ]:
        return False  # Other literals/functions remain outside this NULL-only check.
    if not _on_update_prefix(prefix) or (
        remainder
        and (
            remainder[0].kind != "word"
            or remainder[0].value.lower()
            not in {
                "comment",
                "invisible",
                "on",
                "check",
                "references",
                "unique",
                "primary",
                "not",
                "null",
                "auto_increment",
            }
        )
    ):
        msg = "unsupported MariaDB DEFAULT NULL position or suffix; explicit adapter required"
        raise PackageError(msg)
    return True


def mariadb_declared_default(
    definition: str, *, backslash_escapes: bool = True
) -> tuple[str, object] | None:
    """Read bounded constant/clock defaults without evaluating SQL expressions."""
    column = _COLUMN.match(definition)
    source = str(column[1]) if column is not None else ""
    datatype = _TYPE.match(source)
    if datatype is None:
        msg = "unsupported MariaDB default storage declaration"
        raise PackageError(msg)
    tail = source[datatype.end() :].strip()
    tail = re.sub(
        r"^(?:character\s+set\s+utf8mb4\s+)?(?:collate\s+utf8mb4_[a-z0-9_]+\s+)?",
        "",
        tail,
        flags=re.IGNORECASE | re.ASCII,
    )
    stream = tokens(tail, mysql=backslash_escapes)
    positions: list[int] = []
    depth = 0
    for index, token in enumerate(stream):
        if (token.kind, token.value) == ("punct", "("):
            depth += 1
        elif (token.kind, token.value) == ("punct", ")"):
            depth -= 1
        elif depth == 0 and (token.kind, token.value.lower()) == ("word", "default"):
            positions.append(index)
    if not positions:
        return None
    if len(positions) != 1 or not _on_update_prefix(stream[: positions[0]]):
        msg = "unsupported MariaDB DEFAULT position; explicit adapter required"
        raise PackageError(msg)
    expression = _default_expression(tail, stream, positions[0] + 1)
    return _default_signature(expression, definition)


def mariadb_default_parts(definition: str) -> tuple[str, str | None]:
    """Separate a validated default term, retaining every other declaration byte."""
    stream = tokens(definition, mysql=True)
    end = 0
    for token in stream:
        if definition[end : token.start].strip():
            msg = (
                "SQL comments in native default transitions require an explicit adapter"
            )
            raise PackageError(msg)
        end = token.end
    if definition[end:].strip():
        msg = "SQL comments in native default transitions require an explicit adapter"
        raise PackageError(msg)
    if mariadb_declared_default(definition) is None:
        return definition, None
    depth = 0
    for index, token in enumerate(stream):
        if (token.kind, token.value) == ("punct", "("):
            depth += 1
        elif (token.kind, token.value) == ("punct", ")"):
            depth -= 1
        elif depth == 0 and (token.kind, token.value.lower()) == ("word", "default"):
            expression = _default_expression(definition, stream, index + 1).rstrip()
            end = stream[index + 1].start + len(expression)
            return definition[: token.start].rstrip() + definition[end:], expression
    msg = "unsupported MariaDB default declaration"
    raise PackageError(msg)


def _default_expression(tail: str, stream: tuple[Token, ...], start: int) -> str:
    """Separate a default term from subsequent column attributes without execution."""
    end = len(stream)
    depth = 0
    for index in range(start, len(stream)):
        token = stream[index]
        if (token.kind, token.value) == ("punct", "("):
            depth += 1
        elif (token.kind, token.value) == ("punct", ")"):
            depth -= 1
        elif (
            index > start
            and depth == 0
            and token.kind == "word"
            and token.value.lower() in _ATTRIBUTES
        ):
            end = index
            break
    if start == end:
        msg = "unsupported empty MariaDB DEFAULT"
        raise PackageError(msg)
    return tail[
        stream[start].start : stream[end].start if end < len(stream) else len(tail)
    ]


def _default_signature(expression: str, definition: str) -> tuple[str, object]:
    """Normalize only known literal and compiler clock forms, retaining string identity."""
    stream = tokens(expression, mysql=True)
    while stream and (stream[0].kind, stream[0].value) == ("punct", "("):
        inner = _check_expression(stream)
        if len(inner) != len(stream) - 2:
            break
        stream = inner
        expression = expression[stream[0].start : stream[-1].end] if stream else ""
        stream = tokens(expression, mysql=True)
    # MariaDB SHOW CREATE renders UTF-8 hex CONVERT constants using 0x spelling.
    if match := re.fullmatch(
        r"convert\s*\(\s*0x([0-9a-f]*)\s+using\s+utf8mb4\s*\)",
        expression,
        re.IGNORECASE | re.ASCII,
    ):
        expression = "CONVERT(X'" + str(match[1]) + "' USING utf8mb4)"
    literal = parse_default_literal(expression, mariadb=True)
    family, parameters, _ = _signature(definition, declaration=True)
    if literal is not None and (
        literal.value is None
        or (type(literal.value) is int and family in _INTEGERS)
        or (
            type(literal.value) is str
            and family
            in {"char", "varchar", "tinytext", "text", "mediumtext", "longtext"}
        )
    ):
        return "literal", literal.value
    signature = tuple(
        (t.kind, t.value.lower() if t.kind == "word" else t.value) for t in stream
    )
    if family in {"datetime", "timestamp"}:
        clock = f"CURRENT_TIMESTAMP({parameters[0]})"
    else:
        clock = "CONCAT(REPLACE(CURRENT_TIMESTAMP(6), ' ', 'T'), 'Z')"
        if family not in {
            "char",
            "varchar",
            "tinytext",
            "text",
            "mediumtext",
            "longtext",
        }:
            clock = ""
    if clock and signature == tuple(
        (t.kind, t.value.lower() if t.kind == "word" else t.value)
        for t in tokens(clock, mysql=True)
    ):
        return "clock", signature
    msg = "unsupported MariaDB DEFAULT expression or storage; explicit adapter required"
    raise PackageError(msg)


def mariadb_default_obstacle(
    table: TableState, observed: str, names: tuple[str, ...], *, backslash_escapes: bool
) -> str | None:
    """Compare declared defaults against quoted native DDL, not lossy SHOW COLUMNS text."""
    try:
        _, parts, _ = split_table(observed, mysql=backslash_escapes)
        definitions = {
            name: part
            for part in parts
            if (name := column_name(part, mysql=True)) is not None
        }
        for column, name in zip(table.columns, names, strict=True):
            expected = mariadb_declared_default(column.definition)
            actual = mariadb_declared_default(
                definitions[name], backslash_escapes=backslash_escapes
            )
            # MariaDB normalizes nullable omission to DEFAULT NULL. This proves
            # an effective NULL default, not whether a clause was explicitly written.
            if expected is None and column.nullable and actual == ("literal", None):
                continue
            if expected != actual:
                return f"managed column postcondition failed: {table.name!r}.{column.name!r} default differs from the recorded contract; committed MariaDB effects may remain"
    except (SchemaError, PackageError, KeyError) as error:
        return f"managed table postcondition failed: {table.name!r} has unsupported default metadata: {error}; committed MariaDB effects may remain"
    return None


def _bounded_check_expression(sql: str, inner: tuple[Token, ...]) -> CheckExpression:
    """Bound parsing and normalization before recursive tree work on either input."""
    msg = "general MariaDB CHECK declaration exceeds supported grammar or resource limits; explicit adapter required"
    if not inner or len(inner) > _CHECK_TOKEN_LIMIT:
        raise PackageError(msg)
    depth = 0
    for token in inner:
        if (token.kind, token.value) == ("punct", "("):
            depth += 1
            if depth > _CHECK_PAREN_LIMIT:
                raise PackageError(msg)
        elif (token.kind, token.value) == ("punct", ")"):
            depth -= 1
    expression = parse_check(sql[inner[0].start : inner[-1].end])
    if expression is None or expression.operator in {"literal", "column"}:
        raise PackageError(msg)
    pending = [(expression, 1, 1)]
    work = 0
    while pending:
        node, depth, weight = pending.pop()
        # NOT normalization may visit a subtree again after a De Morgan rewrite.
        weight *= 2 if node.operator == "NOT" else 1
        work += weight
        if depth > _CHECK_TREE_LIMIT or work > _CHECK_WORK_LIMIT:
            raise PackageError(msg)
        pending.extend((child, depth + 1, weight) for child in node.arguments)
    return _normalize_single_membership(normalize_check(expression))


def _normalize_single_membership(expression: CheckExpression) -> CheckExpression:
    """MariaDB renders singleton IN/NOT IN as equality/inequality."""
    arguments = tuple(
        _normalize_single_membership(child) for child in expression.arguments
    )
    operator = expression.operator
    if operator in {"IN", "NOT IN"} and len(arguments) == _SINGLE_MEMBERSHIP_ARITY:
        operator = "eq" if operator == "IN" else "ne"
    return CheckExpression(operator, arguments, expression.value)


def _declared_checks(
    sql: str, json_columns: frozenset[str]
) -> tuple[tuple[str | None, CheckExpression], ...]:
    """Read a finite CHECK language, preserving names and multiplicity."""
    stream = tokens(sql, mysql=True)
    depth = 0
    result: list[tuple[str | None, CheckExpression]] = []
    for index, token in enumerate(stream):
        if (token.kind, token.value) == ("punct", "("):
            depth += 1
        elif (token.kind, token.value) == ("punct", ")"):
            depth -= 1
        elif depth == 0 and (token.kind, token.value.lower()) == ("word", "check"):
            inner = _check_expression(stream[index + 1 :])
            if _json_check_reference(inner) in json_columns:
                continue
            expression = _bounded_check_expression(sql, inner)
            name = None
            if index >= _CONSTRAINT_PREFIX_TOKENS and (
                stream[index - 2].kind,
                stream[index - 2].value.lower(),
            ) == ("word", "constraint"):
                name = stream[index - 1].value
            result.append((name, expression))
    return tuple(result)


def _table_checks(
    table: TableState, sql: str, *, json_columns: frozenset[str] | None = None
) -> tuple[tuple[str | None, CheckExpression], ...]:
    """Collect table and inline declarations without treating a view as a table."""
    prefix = tokens(sql, mysql=True)[:2]
    if tuple((t.kind, t.value.lower()) for t in prefix) != (
        ("word", "create"),
        ("word", "table"),
    ):
        return ()
    parts = split_table(sql, mysql=True)[1]
    if json_columns is None:
        json_columns = frozenset(mariadb_declared_json_columns(table))
    return tuple(
        check for part in parts for check in _declared_checks(part, json_columns)
    )


def _validate_check_claims(table: TableState) -> None:
    """Require supported CHECKs and agreement of redundant column declarations."""
    declared = _table_checks(table, table.sql)
    columns = tuple(
        check
        for column in table.columns
        for check in _declared_checks(
            column.definition, frozenset(mariadb_declared_json_columns(table))
        )
    )
    if Counter(expression for _, expression in columns) - Counter(
        expression for _, expression in declared
    ) or Counter(
        (name, expression) for name, expression in columns if name is not None
    ) - Counter(
        (name, expression) for name, expression in declared if name is not None
    ):
        msg = "recorded column CHECK claims differ from construction SQL; explicit adapter required"
        raise PackageError(msg)


def mariadb_check_obstacle(
    table: TableState, observed: str, names: tuple[str, ...]
) -> str | None:
    """Verify supported CHECK definitions, not session enforcement or existing data."""
    try:
        expected = _table_checks(table, table.sql)
        json_claims = frozenset(mariadb_declared_json_columns(table))
        actual = _table_checks(
            table,
            observed,
            json_columns=frozenset(
                name
                for column, name in zip(table.columns, names, strict=True)
                if column.name in json_claims
            ),
        )
        if Counter(expression for _, expression in expected) != Counter(
            expression for _, expression in actual
        ) or Counter(
            (name, expression) for name, expression in expected if name is not None
        ) - Counter(
            (name, expression) for name, expression in actual if name is not None
        ):
            return f"managed table postcondition failed: {table.name!r} CHECK definitions differ; committed MariaDB effects may remain"
    except (SchemaError, PackageError) as error:
        return f"managed table postcondition failed: {table.name!r} has unsupported CHECK metadata: {error}; committed MariaDB effects may remain"
    return None
