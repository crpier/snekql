"""Execution epoch one: historical target lowering, with live admission checks."""

from typing import Any

from snekql.experimental._migration_checks import (
    add_check,
    drop_check,
)
from snekql.experimental._migration_indexes import (
    validate_index_dependencies,
)
from snekql.experimental._migration_mariadb import validate_mariadb_declarations
from snekql.experimental._migration_prepare import ExecutionStep
from snekql.experimental._migration_reference_parents import (
    validate_sqlite_reference_parents,
)
from snekql.experimental._migration_sql import (
    Token,
    ascii_lower,
    column_name,
    nullable_definition,
    references,
    required_definition,
    split_table,
    tokens,
)
from snekql.experimental.migrations import (
    Contraction,
    Package,
    PackageError,
)
from snekql.sqlite.identifiers import quote_identifier as quote


def prepare_steps(
    package: Package, catalog: list[tuple[Any, ...]]
) -> tuple[ExecutionStep, ...]:
    """Resolve deferred steps; do not open a database or execute authoring code."""
    validate_mariadb_declarations(package.target)
    validate_index_dependencies(package, catalog)
    objects = list(catalog)
    steps: list[ExecutionStep] = []
    for index, (sql, params, transactional, contraction) in enumerate(
        zip(
            package.statements,
            package.bindings,
            package.transactional,
            package.contractions,
            strict=True,
        )
    ):
        if contraction is not None and package.target.backend == "sqlite":
            step, objects = _rebuild(
                contraction, objects, f"_snekql_rebuild_{package.digest[:12]}_{index}"
            )
            steps.append(step)
        else:
            if sql is None:
                msg = "unresolved execution statement"
                raise PackageError(msg)
            steps.append(
                ExecutionStep(
                    statements=(sql,),
                    bindings=(params,),
                    transactional=transactional,
                    required=tuple(
                        (contraction.before.name, name) for name in contraction.required
                    )
                    if contraction
                    else (),
                )
            )
            if package.target.backend == "sqlite":
                objects = _project(sql, objects)
    validate_sqlite_reference_parents(package, objects)
    return tuple(steps)


def _project(sql: str, objects: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    """Track known preceding CREATE/ADD steps so a same-package rebuild sees them."""
    stream = tokens(sql)
    # Keyword lookup must not treat quoted object names as SQL grammar.
    words = [
        ascii_lower(token.value) if token.kind == "word" else None for token in stream
    ]
    if words[:2] == ["drop", "index"]:
        return [
            row
            for row in objects
            if not (row[0] == "index" and row[1] == stream[2].value)
        ]
    if words[:2] == ["create", "table"]:
        name = stream[2].value
        return [*objects, ("table", name, name, sql)]
    if words[:2] == ["create", "index"] or words[:3] == ["create", "unique", "index"]:
        name = stream[words.index("index") + 1].value
        owner = stream[words.index("on") + 1].value
        return [*objects, ("index", name, owner, sql)]
    if words[:2] == ["alter", "table"] and words[3:5] == ["add", "column"]:
        name = stream[2].value
        definition = sql[stream[5].start :]
        projected = []
        for original in objects:
            row = original
            if row[0] == "table" and row[1] == name:
                prefix, parts, suffix = split_table(row[3])
                columns = [part for part in parts if column_name(part) is not None]
                constraints = [part for part in parts if column_name(part) is None]
                sql = (
                    prefix
                    + "("
                    + ", ".join([*columns, definition, *constraints])
                    + ")"
                    + suffix
                )
                row = (row[0], row[1], row[2], sql)
            projected.append(row)
        return projected
    return objects


def _generated(definition: str) -> bool:
    # Only AS(expression) declares generation; GENERATED can be a default literal.
    depth = 0
    stream = tokens(definition)
    for index, token in enumerate(stream[1:-1], start=1):
        if token.kind == "punct" and token.value == "(":
            depth += 1
        elif token.kind == "punct" and token.value == ")":
            depth -= 1
        elif (
            depth == 0
            and token.kind == "word"
            and ascii_lower(token.value) == "as"
            and stream[index + 1].kind == "punct"
            and stream[index + 1].value == "("
        ):
            return True
    return False


def _mentions(sql: str, names: set[str]) -> bool:
    # SQLite permits legacy single-quoted table identifiers. Over-selecting a
    # string literal is safer than missing that dependency.
    folded = {ascii_lower(name) for name in names}
    return any(ascii_lower(token.value) in folded for token in tokens(sql))


def _trigger_update_columns(stream: tuple[Token, ...]) -> tuple[Token, ...]:
    """Read the event-column list, not similarly spelled names or body expressions."""
    words = [
        ascii_lower(token.value) if token.kind == "word" else None for token in stream
    ]
    if words[:2] != ["create", "trigger"]:
        return ()
    start = 2
    if words[start : start + 3] == ["if", "not", "exists"]:
        start += 3
    start += 1  # trigger name (which may itself be a SQL keyword)
    if (
        start < len(stream)
        and stream[start].kind == "punct"
        and stream[start].value == "."
    ):
        start += 2  # optional schema-qualified name
    if words[start : start + 2] == ["instead", "of"]:
        start += 2
    elif words[start : start + 1] in (["before"], ["after"]):
        start += 1
    if words[start : start + 2] != ["update", "of"]:
        return ()
    for end in range(start + 2, len(stream)):
        if words[end] == "on":
            return stream[start + 2 : end]
    return ()


def _dependency_references(sql: str, names: set[str]) -> bool:
    """Recognize bounded legacy identifier positions without treating literals as names."""
    if references(sql, names):
        return True
    stream = tokens(sql)
    folded = {ascii_lower(name) for name in names}
    if any(
        token.kind == "string"
        and ascii_lower(token.value) in folded
        and stream[index - 1].kind == "punct"
        and stream[index - 1].value == "."
        for index, token in enumerate(stream)
        if index > 0
    ):
        return True
    return any(
        ascii_lower(token.value) in folded for token in _trigger_update_columns(stream)
    )


def _views(objects: list[tuple[Any, ...]], table: str) -> list[tuple[Any, ...]]:
    selected: list[tuple[Any, ...]] = []
    names = {table}
    while True:
        more = [
            row
            for row in objects
            if row[0] == "view" and row not in selected and _mentions(row[3], names)
        ]
        if not more:
            return selected
        selected.extend(more)
        names.update(row[1] for row in more)


def _rebuild(
    change: Contraction, objects: list[tuple[Any, ...]], temporary: str
) -> tuple[ExecutionStep, list[tuple[Any, ...]]]:
    table = change.before.name
    if any(row[1] == temporary for row in objects):
        msg = "rebuild staging name already exists"
        raise PackageError(msg)
    source = next(
        (row[3] for row in objects if row[0] == "table" and row[1] == table), None
    )
    if source is None:
        msg = f"missing table {table!r} for contraction"
        raise PackageError(msg)
    observed = change.before.model_copy(update={"sql": source})
    for name in change.removed_checks:
        observed = drop_check(observed, name, "sqlite")
    source = observed.sql
    for definition in change.added_checks:
        observed = add_check(observed, definition, "sqlite")
    _, parts, suffix = split_table(source)
    columns = {
        column_name(part): part for part in parts if column_name(part) is not None
    }
    if (
        not {*change.required, *change.dropped, *change.defaults, *change.relaxed}
        <= columns.keys()
    ):
        msg = f"{table}: contraction columns are missing"
        raise PackageError(msg)
    retained = [part for part in parts if column_name(part) not in change.dropped]
    views = _views(objects, table)
    related = {table, *(row[1] for row in views)}
    associated = [
        row
        for row in objects
        if row[3] is not None
        and (
            (row[0] == "index" and row[2] == table)
            or (row[0] == "trigger" and (row[2] == table or _mentions(row[3], related)))
        )
    ]
    if change.dropped and any(
        token.kind == "punct" and token.value == "*"
        for row in (*views, *(item for item in associated if item[0] == "trigger"))
        for token in tokens(row[3])
    ):
        msg = f"{table}: wildcard dependencies require explicit resolution before column removal"
        raise PackageError(msg)
    dropped = set(change.dropped)
    dependencies = [
        *retained,
        *(row[3] for row in associated),
        *(row[3] for row in views),
    ]
    dependencies.extend(
        row[3]
        for row in objects
        if row[0] == "table" and row[1] != table and references(row[3], {table})
    )
    if any(_dependency_references(sql, dropped) for sql in dependencies):
        msg = f"{table}: a constraint, index, trigger, view or referencing table depends on removed columns"
        raise PackageError(msg)
    revised = [
        required_definition(part) if column_name(part) in change.required else part
        for part in retained
    ]
    revised = [
        nullable_definition(part) if column_name(part) in change.relaxed else part
        for part in revised
    ]
    revised = [
        next(
            column.definition
            for column in change.after.columns
            if column.name == column_name(part)
        )
        if column_name(part) in change.defaults
        else part
        for part in revised
    ]
    revised.extend(change.added_checks)
    copied = [
        column_name(part)
        for part in retained
        if column_name(part) is not None and not _generated(part)
    ]
    copy_columns = tuple(str(name) for name in copied)
    if not references(suffix, {"without"}):
        rowid = next(
            (
                name
                for name in ("_rowid_", "rowid", "oid")
                if name not in {ascii_lower(str(col)) for col in columns}
            ),
            None,
        )
        if rowid is None:
            msg = f"{table}: hidden row identity cannot be preserved"
            raise PackageError(msg)
        copied.append(rowid)
    names = ", ".join(quote(str(name)) for name in copied)
    statements = [f"DROP VIEW {quote(row[1])}" for row in views]
    statements.extend(
        f"DROP TRIGGER {quote(row[1])}" for row in associated if row[0] == "trigger"
    )
    statements.append(
        f"CREATE TABLE {quote(temporary)} (" + ", ".join(revised) + ")" + suffix
    )
    copy_at = len(statements)
    statements.extend(
        (
            f"INSERT INTO {quote(temporary)} ({names}) SELECT {names} FROM {quote(table)}",  # noqa: S608 - fixed placeholders or quoted identifiers
            f"DROP TABLE {quote(table)}",
            f"ALTER TABLE {quote(temporary)} RENAME TO {quote(table)}",
            *(row[3] for row in associated),
            *(row[3] for row in views),
            *(
                f"SELECT * FROM {quote(row[1])} LIMIT 0"  # noqa: S608 - fixed placeholders or quoted identifiers
                for row in objects
                if row[0] == "view"
            ),
        )
    )
    new_sql = f"CREATE TABLE {quote(table)} (" + ", ".join(revised) + ")" + suffix
    projected = [
        (row[0], row[1], row[2], new_sql)
        if row[0] == "table" and row[1] == table
        else row
        for row in objects
    ]
    return ExecutionStep(
        statements=tuple(statements),
        bindings=tuple(() for _ in statements),
        rebuild=True,
        required=tuple((table, name) for name in change.required),
        sequence_table=table if references(source, {"autoincrement"}) else None,
        copy_tables=(table, temporary),
        copy_at=copy_at,
        copy_columns=copy_columns,
        dropped_columns=change.dropped,
        validate_triggers=True,
    ), projected
