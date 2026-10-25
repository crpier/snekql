"""Execution epoch one: canonical legacy emission, independent of public authoring.

Formats 2 through 8 name this interpretation. Preserve accepted execution bytes
or refuse; do not reinterpret them with a future authoring compiler. Current
construction/admission validation stays live, not frozen as a correctness claim.
"""

from collections.abc import Iterable, Iterator
from itertools import chain

from snekql.experimental._migration_indexes import add_index, drop_index
from snekql.experimental._migration_mariadb import mariadb_default_parts
from snekql.experimental.migrations import (
    _RESERVED,
    AddCheck,
    AddColumn,
    AdoptTable,
    AllowNull,
    Backend,
    ChangeDefault,
    Checkpoint,
    Contraction,
    CreateIndex,
    CreateTable,
    DataChange,
    Draft,
    DropCheck,
    DropColumn,
    DropIndex,
    Package,
    PackageError,
    Parameter,
    RelinquishTable,
    RequireNotNull,
    TableState,
    _add_column,
    _auxiliary_change,
    _contract_table,
    _digest,
    _managed_table,
    _relinquish,
    _state_digest,
    _validate_draft,
)


def _validate_data_change(
    operation: DataChange,
    draft: Draft,
    checkpoints: dict[str, str],
    tables: dict[str, TableState],
) -> None:
    if (
        checkpoints.get(operation.checkpoint) != operation.contract_digest
        or _state_digest(draft.target.backend, tables) != operation.contract_digest
        or operation.backend != draft.target.backend
        or not operation.sql.startswith("UPDATE ")
        or any(name in operation.sql.casefold() for name in _RESERVED)
    ):
        msg = "data change has a stale or mismatched intermediate contract"
        raise PackageError(msg)


class _Emission:
    def __init__(self, backend: Backend, sql_bytes: int) -> None:
        self.backend = backend
        self.sql_bytes = sql_bytes
        self.statements: list[str | None] = []
        self.bindings: list[tuple[Parameter, ...]] = []
        self.transactional: list[bool] = []
        self.contractions: list[Contraction | None] = []
        self.pending: Contraction | None = None
        self.relinquished: set[str] = set()

    def emit(
        self,
        sql: str,
        params: tuple[Parameter, ...] = (),
        *,
        transactional: bool = False,
    ) -> None:
        self.flush()
        self.sql_bytes = _check_sql_budget((sql,), self.sql_bytes)
        self.statements.append(sql)
        self.bindings.append(params)
        self.transactional.append(transactional)
        self.contractions.append(None)

    def contract(
        self,
        before: TableState,
        after: TableState,
        operation: RequireNotNull | AllowNull | DropColumn | ChangeDefault,
    ) -> None:
        if self.pending is not None and self.pending.before.name != before.name:
            self.flush()
        pending = self.pending or Contraction(before=before, after=after)
        if (
            isinstance(operation, AllowNull)
            and operation.column_name in pending.required
        ) or (
            isinstance(operation, RequireNotNull)
            and operation.column_name in pending.relaxed
        ):
            msg = "opposing nullability transitions require a checkpoint"
            raise PackageError(msg)
        self.pending = pending.model_copy(
            update={
                "after": after,
                "required": (*pending.required, operation.column_name)
                if isinstance(operation, RequireNotNull)
                else pending.required,
                "dropped": (*pending.dropped, operation.column_name)
                if isinstance(operation, DropColumn)
                else pending.dropped,
                "relaxed": (*pending.relaxed, operation.column_name)
                if isinstance(operation, AllowNull)
                else pending.relaxed,
                "defaults": (*pending.defaults, operation.column_name)
                if isinstance(operation, ChangeDefault)
                else pending.defaults,
            }
        )

    def flush(self) -> None:
        pending = self.pending
        if pending is None:
            return
        self.sql_bytes = _check_sql_budget(
            chain(
                _table_sql(pending.before),
                _table_sql(pending.after),
                pending.added_checks,
            ),
            self.sql_bytes,
        )
        clauses = [
            "MODIFY COLUMN "
            + next(c.definition for c in pending.after.columns if c.name == name)
            for name in dict.fromkeys((*pending.required, *pending.relaxed))
            if name not in pending.dropped
        ]
        clauses.extend(
            "DROP COLUMN `" + name.replace("`", "``") + "`" for name in pending.dropped
        )
        if self.backend == "mariadb":
            for name in dict.fromkeys(pending.defaults):
                if name in (*pending.required, *pending.relaxed, *pending.dropped):
                    continue
                column = next(c for c in pending.after.columns if c.name == name)
                _, expression = mariadb_default_parts(column.definition)
                action = (
                    "DROP DEFAULT"
                    if expression is None
                    else "SET DEFAULT " + expression
                )
                clauses.append(
                    "ALTER COLUMN `" + name.replace("`", "``") + "` " + action
                )
        clauses.extend("ADD " + definition for definition in pending.added_checks)
        clauses.extend(
            "DROP CONSTRAINT `" + name.replace("`", "``") + "`"
            for name in pending.removed_checks
        )
        sql = (
            None
            if self.backend == "sqlite"
            else f"ALTER TABLE {pending.before.quoted_name} " + ", ".join(clauses)
        )
        if sql is not None:
            self.sql_bytes = _check_sql_budget((sql,), self.sql_bytes)
        self.statements.append(sql)
        self.bindings.append(())
        self.transactional.append(False)
        self.contractions.append(pending)
        self.pending = None


def _emit_table(
    operation: CreateTable
    | AdoptTable
    | CreateIndex
    | DropIndex
    | AddCheck
    | DropCheck,
    tables: dict[str, TableState],
    emission: _Emission,
) -> None:
    if isinstance(operation, AddCheck | DropCheck):
        emission.flush()
        table = _managed_table(tables, operation.table_name)
        after = _auxiliary_change(table, operation, emission.backend)
        tables[operation.table_name] = after
        emission.pending = Contraction(
            before=table,
            after=after,
            added_checks=(operation.definition,)
            if isinstance(operation, AddCheck)
            else (),
            removed_checks=(operation.check_name,)
            if isinstance(operation, DropCheck)
            else (),
        )
        emission.flush()
        return
    if isinstance(operation, DropIndex):
        table = _managed_table(tables, operation.table_name)
        tables[operation.table_name] = drop_index(
            table, operation.index_name, emission.backend
        )
        name = "`" + operation.index_name.replace("`", "``") + "`"
        suffix = " ON " + table.quoted_name if emission.backend == "mariadb" else ""
        emission.emit("DROP INDEX " + name + suffix)
        return
    if isinstance(operation, CreateIndex):
        table = _managed_table(tables, operation.table_name)
        tables[operation.table_name] = add_index(table, operation.sql, emission.backend)
        emission.emit(operation.sql)
        return
    table = operation.table
    if isinstance(operation, AdoptTable):
        _emit_adoption(table, tables, emission)
        return
    if table.name in emission.relinquished:
        msg = f"table {table.name!r} remains physically present after relinquishment; explicit adoption is required"
        raise PackageError(msg)
    if table.name in tables:
        msg = f"table {table.name!r} already exists in managed state"
        raise PackageError(msg)
    tables[table.name] = table
    for sql in (table.sql, *table.indexes):
        emission.emit(sql)


def _emit_adoption(
    table: TableState, tables: dict[str, TableState], emission: _Emission
) -> None:
    if emission.backend != "sqlite":
        msg = "table adoption currently supports SQLite only"
        raise PackageError(msg)
    if table.name in tables or table.name in emission.relinquished:
        msg = "adoption requires a table not already managed or relinquished in this route"
        raise PackageError(msg)
    emission.flush()
    tables[table.name] = table


def _table_sql(table: TableState) -> Iterator[str]:
    yield table.sql
    yield from table.indexes
    yield from (column.definition for column in table.columns)


def _draft_sql(draft: Draft) -> Iterator[str]:
    """Visit SQL occurrences, not unique strings, without copying the whole draft."""
    for state in (draft.before, draft.target):
        for table in state.tables:
            yield from _table_sql(table)
    for operation in draft.operations:
        if isinstance(operation, CreateTable | AdoptTable):
            yield from _table_sql(operation.table)
        elif isinstance(operation, AddColumn | ChangeDefault):
            yield operation.column.definition
        elif isinstance(operation, AddCheck):
            yield operation.definition
        elif isinstance(operation, DataChange | CreateIndex):
            yield operation.sql


def _check_sql_budget(sources: Iterable[str], used: int = 0) -> int:
    """Bound individual sources and cumulative occurrences, including emitted SQL."""
    limit = 1024 * 1024
    for sql in sources:
        size = len(sql.encode("utf-8")) if len(sql) <= limit else len(sql)
        if size > limit:
            msg = "migration SQL source exceeds UTF-8 byte limit (1 MiB)"
            raise PackageError(msg)
        used += size
        if used > 4 * limit:
            msg = "migration aggregate SQL exceeds UTF-8 byte limit (4 MiB)"
            raise PackageError(msg)
    return used


def compile_v1(draft: Draft) -> Package:
    """Validate the route and freeze SQL; never import current application models."""
    sql_bytes = _check_sql_budget(_draft_sql(draft))
    _validate_draft(draft)
    tables = {table.name: table for table in draft.before.tables}
    emission = _Emission(draft.target.backend, sql_bytes)
    checkpoints: dict[str, str] = {}
    for operation in draft.operations:
        if isinstance(operation, RelinquishTable):
            emission.flush()
            _relinquish(tables, operation.table_name)
            emission.relinquished.add(operation.table_name)
            continue
        if isinstance(
            operation, RequireNotNull | AllowNull | DropColumn | ChangeDefault
        ):
            before = _managed_table(tables, operation.table_name)
            after = _contract_table(before, operation, draft.target.backend)
            tables[operation.table_name] = after
            emission.contract(before, after, operation)
            continue
        if isinstance(operation, Checkpoint):
            emission.flush()
            if not operation.name or operation.name in checkpoints:
                msg = "checkpoint names must be nonempty and unique"
                raise PackageError(msg)
            checkpoints[operation.name] = _state_digest(draft.target.backend, tables)
            continue
        if isinstance(operation, DataChange):
            _validate_data_change(operation, draft, checkpoints, tables)
            emission.emit(operation.sql, operation.params, transactional=True)
            continue
        if isinstance(operation, AddColumn):
            if operation.table_name not in tables:
                msg = "cannot add column to an unmanaged table"
                raise PackageError(msg)
            current = tables[operation.table_name]
            tables[operation.table_name] = _add_column(current, operation.column)
            emission.emit(
                f"ALTER TABLE {current.quoted_name} ADD COLUMN {operation.column.definition}"
            )
            continue
        _emit_table(operation, tables, emission)
    if tables != {table.name: table for table in draft.target.tables}:
        msg = "operation endpoint does not match the recorded target state"
        raise PackageError(msg)
    emission.flush()
    version = (
        8
        if any(isinstance(op, DropCheck) for op in draft.operations)
        else 7
        if any(isinstance(op, AddCheck) for op in draft.operations)
        else 6
        if any(isinstance(op, DropIndex) for op in draft.operations)
        else 5
        if any(isinstance(op, CreateIndex) for op in draft.operations)
        else 4
        if any(isinstance(op, AllowNull) for op in draft.operations)
        else 3
        if any(isinstance(op, ChangeDefault) for op in draft.operations)
        else 2
    )
    payload = {
        "version": version,
        "draft": draft.model_dump(mode="json"),
        "statements": emission.statements,
        "bindings": emission.bindings,
        "transactional": emission.transactional,
        "contractions": [
            item.model_dump(mode="json") if item else None
            for item in emission.contractions
        ],
    }
    return Package(
        version=version,
        draft=draft,
        statements=tuple(emission.statements),
        bindings=tuple(emission.bindings),
        transactional=tuple(emission.transactional),
        contractions=tuple(emission.contractions),
        digest=_digest(payload),
    )
