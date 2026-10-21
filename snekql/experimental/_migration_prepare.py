"""Prepare bounded SQLite rebuilds from complete observed CREATE definitions."""

from collections import Counter
from typing import Any

from snekql.errors import SchemaError
from snekql.experimental._migration_sql import (
    column_name,
    references,
    required_definition,
    split_table,
    tokens,
)
from snekql.experimental.migrations import (
    AdoptTable,
    Contraction,
    Package,
    PackageError,
    Parameter,
    _Value,
)
from snekql.sqlite.identifiers import quote_identifier as quote


class ExecutionStep(_Value):
    """One progress unit, possibly several transactional SQLite rebuild statements."""

    statements: tuple[str, ...]
    bindings: tuple[tuple[Parameter, ...], ...]
    transactional: bool = False
    required: tuple[tuple[str, str], ...] = ()
    rebuild: bool = False
    sequence_table: str | None = None
    copy_tables: tuple[str, str] | None = None
    copy_at: int | None = None
    validate_triggers: bool = False


def prepare_steps(
    package: Package, catalog: list[tuple[Any, ...]]
) -> tuple[ExecutionStep, ...]:
    """Resolve deferred steps; do not open a database or execute authoring code."""
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
    return tuple(steps)


def _project(sql: str, objects: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    """Track known preceding CREATE/ADD steps so a same-package rebuild sees them."""
    stream = tokens(sql)
    words = [token.value.casefold() for token in stream]
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
    depth = 0
    for token in tokens(definition)[1:]:
        if token.kind == "punct" and token.value == "(":
            depth += 1
        elif token.kind == "punct" and token.value == ")":
            depth -= 1
        elif (
            depth == 0
            and token.kind == "word"
            and token.value.casefold() in {"as", "generated"}
        ):
            return True
    return False


def _mentions(sql: str, names: set[str]) -> bool:
    # SQLite permits legacy single-quoted table identifiers. Over-selecting a
    # string literal is safer than missing that dependency.
    folded = {name.casefold() for name in names}
    return any(token.value.casefold() in folded for token in tokens(sql))


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
    _, parts, suffix = split_table(source)
    columns = {
        column_name(part): part for part in parts if column_name(part) is not None
    }
    if not {*change.required, *change.dropped} <= columns.keys():
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
    if any(references(sql, dropped) for sql in dependencies):
        msg = f"{table}: a constraint, index, trigger, view or referencing table depends on removed columns"
        raise PackageError(msg)
    revised = [
        required_definition(part) if column_name(part) in change.required else part
        for part in retained
    ]
    copied = [
        column_name(part)
        for part in retained
        if column_name(part) is not None and not _generated(part)
    ]
    if not references(suffix, {"without"}):
        rowid = next(
            (
                name
                for name in ("_rowid_", "rowid", "oid")
                if name not in {str(col).casefold() for col in columns}
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
        validate_triggers=True,
    ), projected


def _signature(sql: str) -> tuple[tuple[str, str], ...]:
    return tuple(
        (token.kind, token.value.casefold() if token.kind == "word" else token.value)
        for token in tokens(sql)
    )


def validate_preserved(package: Package, objects: list[tuple[Any, ...]]) -> None:
    """Allow unmanaged additions only after validating every recorded managed fact."""
    for table in package.draft.before.tables:
        actual = next(
            (row[3] for row in objects if row[0] == "table" and row[1] == table.name),
            None,
        )
        if actual is None:
            msg = f"managed table {table.name!r} is missing"
            raise PackageError(msg)
        _, expected_parts, expected_suffix = split_table(table.sql)
        _, actual_parts, actual_suffix = split_table(actual)
        actual_signatures = {_part_signature(part) for part in actual_parts}
        if _signature(expected_suffix) != _signature(actual_suffix) or any(
            _part_signature(part) not in actual_signatures for part in expected_parts
        ):
            msg = (
                f"{table.name}: preservation cannot accept changed managed definitions"
            )
            raise PackageError(msg)
        indexes = {
            _signature(row[3])
            for row in objects
            if row[0] == "index" and row[2] == table.name and row[3] is not None
        }
        if any(_signature(sql) not in indexes for sql in table.indexes):
            msg = f"{table.name}: a managed index has changed or disappeared"
            raise PackageError(msg)


def _part_signature(sql: str) -> tuple[str | None, tuple[tuple[str, str], ...]]:
    name = column_name(sql)
    # A bare column name and its quoted spelling designate the same identifier.
    # Other expressions remain conservative token comparisons, not guessed SQL
    # equivalence; strings, defaults and constraints keep their actual contents.
    tail = sql[tokens(sql)[0].end :] if name is not None else sql
    return name, _signature(tail)


def validate_adopted(package: Package, objects: list[tuple[Any, ...]]) -> None:
    """Prove bounded SQLite adoption against observation, without executing DDL."""
    for operation in package.draft.operations:
        if not isinstance(operation, AdoptTable):
            continue
        table = operation.table
        actual = next(
            (row[3] for row in objects if row[0] == "table" and row[1] == table.name),
            None,
        )
        if actual is None:
            msg = f"adoption requires an existing table {table.name!r}"
            raise PackageError(msg)
        try:
            _, expected_parts, expected_suffix = split_table(table.sql)
            _, actual_parts, actual_suffix = split_table(actual)
            differences = []
            expected = Counter(_part_signature(part) for part in expected_parts)
            observed = Counter(_part_signature(part) for part in actual_parts)
            if expected != observed:
                names = sorted(
                    {
                        name or "<table constraint>"
                        for name, _ in (*(expected - observed), *(observed - expected))
                    }
                )
                differences.append(
                    "column/constraint declarations: " + ", ".join(names)
                )
            if _signature(expected_suffix) != _signature(actual_suffix):
                differences.append("table storage options")
            if Counter(_signature(sql) for sql in table.indexes) != Counter(
                _signature(row[3])
                for row in objects
                if row[0] == "index" and row[2] == table.name and row[3] is not None
            ):
                differences.append("index declarations")
            if any(row[0] == "trigger" and row[2] == table.name for row in objects):
                differences.append("unmanaged triggers")
        except SchemaError as error:
            msg = f"{table.name}: adoption cannot interpret the observed definition"
            raise PackageError(msg) from error
        if differences:
            msg = f"{table.name}: adoption cannot accept " + "; ".join(differences)
            raise PackageError(msg)
