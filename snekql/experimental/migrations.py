"""Experimental recorded-state migration authoring and frozen execution packages.

Format 2 is a prototype, not a supported long-term interchange contract. Models
are consulted only during generation; loading execution packages imports none.
"""

import hashlib
import json
import keyword
from collections.abc import Sequence
from typing import Any, Literal, Self, get_args

from pydantic import BaseModel, ConfigDict, ValidationError

from snekql._scaffold import require_scaffold_models
from snekql._schema_compile import compile_create_index_sql, compile_create_table_sql
from snekql._schema_plan import build_schema_plan
from snekql.errors import SnekqlError
from snekql.experimental._migration_sql import references, required_definition
from snekql.model import Table
from snekql.query import Write
from snekql.storage import _extract_logical_type, _resolve_model_hint
lazy from snekql.experimental._migration_target import (
    Prepared,
    Progress,
    Recovery,
    Target,
    connect,
)
lazy from snekql.mariadb.schema import _SCHEMA_DIALECT as MARIADB_DIALECT
lazy from snekql.sqlite._schema_ddl import SCHEMA_DIALECT as SQLITE_DIALECT

type Backend = Literal["sqlite", "mariadb"]


class PackageError(SnekqlError, ValueError):
    """An experimental migration is unresolved, inconsistent, or unsupported."""


class _Value(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ColumnState(_Value):
    """Frozen physical column declaration; not a Python codec contract."""

    name: str
    definition: str
    nullable: bool
    query_type: str | None = None
    storage: str


class TableState(_Value):
    """Frozen managed table construction, independent of application models."""

    name: str
    sql: str
    indexes: tuple[str, ...] = ()
    columns: tuple[ColumnState, ...] = ()
    quoted_name: str


class State(_Value):
    """Recorded managed structure, not an observed catalog or ownership inference."""

    backend: Backend
    tables: tuple[TableState, ...] = ()


class CreateTable(_Value):
    """Create one explicitly managed table and its declared indexes."""

    kind: Literal["create_table"] = "create_table"
    table: TableState


class AddColumn(_Value):
    """Add one unconstrained nullable column without rebuilding a table."""

    kind: Literal["add_column"] = "add_column"
    table_name: str
    column: ColumnState


class RequireNotNull(_Value):
    """Require a populated managed column; execution checks existing data first."""

    kind: Literal["require_not_null"] = "require_not_null"
    table_name: str
    column_name: str


class DropColumn(_Value):
    """Explicit authorization to remove one managed column, not its dependencies."""

    kind: Literal["drop_column"] = "drop_column"
    table_name: str
    column_name: str


class Contraction(_Value):
    """A grouped table transition requiring backend-aware execution planning."""

    before: TableState
    after: TableState
    required: tuple[str, ...] = ()
    dropped: tuple[str, ...] = ()


class Checkpoint(_Value):
    """Name a schema point for generating static query declarations during drafting."""

    kind: Literal["checkpoint"] = "checkpoint"
    name: str


type Parameter = str | int | float | bool | None


class DataChange(_Value):
    """A frozen parameterized UPDATE authored against a named historical contract.

    The supplied contract digest detects stale declarations, not SQL correctness.
    Only trusted query-builder output and JSON scalar bindings are supported.
    """

    kind: Literal["data_change"] = "data_change"
    checkpoint: str
    contract_digest: str
    backend: Backend
    sql: str
    params: tuple[Parameter, ...]

    @classmethod
    def from_query(
        cls, query: Write[int], *, checkpoint: str, contract_digest: str
    ) -> Self:
        """Compile a typed UPDATE once, during authoring rather than deployment."""
        compiled = query.compile()
        if not compiled.sql.startswith("UPDATE "):
            msg = "the initial data-change prototype supports typed UPDATE queries only"
            raise PackageError(msg)
        return cls.model_validate(
            {
                "checkpoint": checkpoint,
                "contract_digest": contract_digest,
                "backend": compiled.backend,
                "sql": compiled.sql,
                "params": compiled.params,
            }
        )


class Draft(_Value):
    """Editable transition; unresolved decisions prevent compilation."""

    revision: str
    predecessor: str | None
    before: State
    target: State
    operations: tuple[
        CreateTable | AddColumn | RequireNotNull | DropColumn | Checkpoint | DataChange,
        ...,
    ]
    unresolved: tuple[str, ...] = ()

    def then(
        self,
        *operations: CreateTable
        | AddColumn
        | RequireNotNull
        | DropColumn
        | Checkpoint
        | DataChange,
    ) -> Self:
        """Append typed authoring steps while retaining the original immutable draft."""
        return self.model_copy(update={"operations": (*self.operations, *operations)})

    def resolve(self, *removals: DropColumn) -> Self:
        """Authorize only the named pending removals; retain other unresolved decisions."""
        unresolved = list(self.unresolved)
        for removal in removals:
            decision = _drop_decision(removal.table_name, removal.column_name)
            if decision not in unresolved:
                msg = f"no pending removal decision for {removal.table_name}.{removal.column_name}"
                raise PackageError(msg)
            unresolved.remove(decision)
        return self.model_copy(
            update={
                "operations": (*self.operations, *removals),
                "unresolved": tuple(unresolved),
            }
        )


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


class Package(_Value):
    """Frozen execution plus historical contracts, with a content-integrity digest.

    Digests detect changes, not malicious publishers. Load only trusted packages.
    """

    version: Literal[2] = 2
    draft: Draft
    statements: tuple[str | None, ...]
    contractions: tuple[Contraction | None, ...]
    bindings: tuple[tuple[Parameter, ...], ...]
    transactional: tuple[bool, ...]
    digest: str

    @property
    def target(self) -> State:
        """Return the recorded destination contract without replaying history."""
        return self.draft.target

    def dump(self) -> str:
        """Serialize a complete model-independent deployment package."""
        return (
            json.dumps(
                self.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n"
        )

    def check(self, draft: Draft) -> None:
        """Reject a deployment artifact that no longer matches supplied authoring."""
        if self != compile(draft):
            msg = "compiled package is stale or inconsistent; recompile the reviewed draft"
            raise PackageError(msg)

    @classmethod
    def load(cls, text: str) -> Self:
        """Reject corrupt, unsupported, or internally inconsistent packages."""
        try:
            package = cls.model_validate_json(text)
        except ValidationError as error:
            msg = "invalid or unsupported execution package format"
            raise PackageError(msg) from error
        expected = compile(package.draft)
        if package != expected:
            msg = "execution package integrity or state consistency mismatch"
            raise PackageError(msg)
        return package


def generate(
    revision: str,
    models: Sequence[type[Table[Any]]],
    *,
    backend: Backend,
    previous: Package | None = None,
) -> Draft:
    """Draft changes against recorded intent, never against a developer database.

    Unsupported alterations and ownership removal remain explicit unresolved
    decisions. Supported routes include creation, nullable additions, typed backfills, and contraction.
    """
    require_scaffold_models(backend, models)
    if previous is not None:
        Package.load(previous.dump())
        if revision == previous.draft.revision:
            msg = "successive revisions must have distinct identities"
            raise PackageError(msg)
    dialect = SQLITE_DIALECT if backend == "sqlite" else MARIADB_DIALECT

    before = previous.target if previous else State(backend=backend)
    if before.backend != backend:
        msg = "previous package belongs to another backend"
        raise PackageError(msg)
    tables = tuple(
        TableState(
            name=table.table_name,
            quoted_name=dialect.quote_identifier(table.table_name),
            columns=tuple(
                ColumnState(
                    name=column.name,
                    definition=dialect.compile_column_definition(column),
                    nullable=column.column.nullable is True,
                    query_type=_query_type(table.model, column.name),
                    storage=column.column.storage_class,
                )
                for column in table.columns
            ),
            sql=compile_create_table_sql(table, dialect),
            indexes=tuple(
                compile_create_index_sql(table.table_name, index, dialect)
                for index in table.indexes
            ),
        )
        for table in build_schema_plan(models).models
    )
    old = {table.name: table for table in before.tables}
    desired = {table.name: table for table in tables}
    unresolved = [
        f"{name}: deletion versus relinquishing ownership requires a decision"
        for name in old.keys() - desired.keys()
    ]
    operations: list[CreateTable | AddColumn | RequireNotNull] = []
    for table in tables:
        if table.name not in old:
            operations.append(CreateTable(table=table))
        elif old[table.name] != table:
            try:
                candidates, removed = _changes(old[table.name], table, backend)
            except PackageError:
                unresolved.append(
                    f"{table.name}: alteration requires a supported structured operation"
                )
            else:
                operations.extend(candidates)
                unresolved.extend(_drop_decision(table.name, name) for name in removed)
    return Draft(
        revision=revision,
        predecessor=previous.digest if previous else None,
        before=before,
        target=State(backend=backend, tables=tables),
        operations=tuple(operations),
        unresolved=tuple(sorted(unresolved)),
    )


def _changes(
    current: TableState, desired: TableState, backend: Backend
) -> tuple[list[AddColumn | RequireNotNull], list[str]]:
    candidates: list[AddColumn | RequireNotNull] = []
    removed = [
        column.name
        for column in current.columns
        if column.name not in {item.name for item in desired.columns}
    ]
    for column in desired.columns:
        existing = next(
            (item for item in current.columns if item.name == column.name), None
        )
        if existing is None:
            change = AddColumn(table_name=desired.name, column=column)
            current = _add_column(current, column)
            candidates.append(change)
        elif existing != column:
            change = RequireNotNull(table_name=desired.name, column_name=column.name)
            current = _contract_table(current, change, backend)
            candidates.append(change)
    for name in removed:
        current = _contract_table(
            current, DropColumn(table_name=desired.name, column_name=name), backend
        )
    if current != desired:
        msg = "alteration is not representable by supported operations"
        raise PackageError(msg)
    return candidates, removed


def _drop_decision(table: str, column: str) -> str:
    return f"{table}.{column}: explicit DropColumn required"


def _contract_table(
    table: TableState, operation: RequireNotNull | DropColumn, backend: Backend
) -> TableState:
    column = next(
        (item for item in table.columns if item.name == operation.column_name), None
    )
    if column is None:
        msg = f"unknown managed column {table.name}.{operation.column_name}"
        raise PackageError(msg)
    prefix = f"CREATE TABLE {table.quoted_name} (" + ", ".join(
        item.definition for item in table.columns
    )
    if not table.sql.startswith(prefix):
        msg = "recorded table and column definitions disagree"
        raise PackageError(msg)
    tail = table.sql[len(prefix) :]
    if isinstance(operation, DropColumn):
        dependencies = (
            tail,
            *table.indexes,
            *(item.definition for item in table.columns if item != column),
        )
        if references(
            column.definition,
            {"primary", "unique", "references"},
            mysql=backend == "mariadb",
        ) or any(
            references(sql, {column.name}, mysql=backend == "mariadb")
            for sql in dependencies
        ):
            msg = f"{table.name}.{column.name}: remove dependent constraints/indexes explicitly"
            raise PackageError(msg)
        columns = tuple(item for item in table.columns if item != column)
    else:
        if not column.nullable:
            msg = f"{table.name}.{column.name} is already required"
            raise PackageError(msg)
        required = column.model_copy(
            update={
                "nullable": False,
                "definition": required_definition(
                    column.definition, mysql=backend == "mariadb"
                ),
                "query_type": " | ".join(
                    part for part in column.query_type.split(" | ") if part != "None"
                )
                if column.query_type
                else None,
            }
        )
        columns = tuple(required if item == column else item for item in table.columns)
    if not columns:
        msg = "cannot remove every column from a table"
        raise PackageError(msg)
    sql = (
        f"CREATE TABLE {table.quoted_name} ("
        + ", ".join(item.definition for item in columns)
        + tail
    )
    return table.model_copy(update={"columns": columns, "sql": sql})


def _query_type(model: type[Table[Any]], name: str) -> str | None:
    logical = _extract_logical_type(_resolve_model_hint(model, name), name)
    types = get_args(logical) or (logical,)
    supported: dict[object, str] = {
        int: "int",
        str: "str",
        float: "float",
        bytes: "bytes",
        bool: "bool",
        type(None): "None",
    }
    if any(value not in supported for value in types):
        return None
    return " | ".join(supported[value] for value in types)


def contract_source(draft: Draft, *, point: str, table: str) -> str:
    """Emit a standalone static query model at a named draft checkpoint.

    Only built-in scalar contracts are supported; custom codecs never silently
    degrade to their physical storage types. No application code is imported.
    """
    tables = {item.name: item for item in draft.before.tables}
    for operation in draft.operations:
        if isinstance(operation, CreateTable):
            tables[operation.table.name] = operation.table
        elif isinstance(operation, AddColumn):
            tables[operation.table_name] = _add_column(
                tables[operation.table_name], operation.column
            )
        elif isinstance(operation, RequireNotNull | DropColumn):
            tables[operation.table_name] = _contract_table(
                tables[operation.table_name], operation, draft.target.backend
            )
        elif isinstance(operation, Checkpoint) and operation.name == point:
            if table not in tables:
                msg = f"table {table!r} is not present at checkpoint {point!r}"
                raise PackageError(msg)
            return (
                _contract_source(tables[table], draft.target.backend)
                + f"\nCONTRACT_DIGEST = {contract_digest(draft, point=point)!r}\n"
            )
    msg = f"unknown checkpoint {point!r}"
    raise PackageError(msg)


def contract_digest(draft: Draft, *, point: str) -> str:
    """Identify a named draft query contract without importing a generated module."""
    tables = {table.name: table for table in draft.before.tables}
    for operation in draft.operations:
        if isinstance(operation, CreateTable):
            tables[operation.table.name] = operation.table
        elif isinstance(operation, AddColumn):
            tables[operation.table_name] = _add_column(
                tables[operation.table_name], operation.column
            )
        elif isinstance(operation, RequireNotNull | DropColumn):
            tables[operation.table_name] = _contract_table(
                tables[operation.table_name], operation, draft.target.backend
            )
        elif isinstance(operation, Checkpoint) and operation.name == point:
            return _state_digest(draft.target.backend, tables)
    msg = f"unknown checkpoint {point!r}"
    raise PackageError(msg)


def _state_digest(backend: Backend, tables: dict[str, TableState]) -> str:
    return _digest(
        State(
            backend=backend, tables=tuple(tables[name] for name in sorted(tables))
        ).model_dump(mode="json")
    )


def _contract_source(table: TableState, backend: Backend) -> str:
    constructors = {
        "INTEGER": "Integer",
        "TEXT": "Text",
        "REAL": "Real",
        "BLOB": "Blob",
    }
    lines = [
        '"""Generated historical query declarations; regenerate after editing the route."""',
        "from typing import ClassVar",
        f"from snekql import {backend}",
        "",
        f"class Historical[S = {backend}.Pending]({backend}.Model[S]):",
        '    """Query-only historical contract, not a schema ownership declaration."""',
        f"    __tablename__ = {table.name!r}",
        f"    __row_type__: ClassVar[{backend}.ReadType[Historical[{backend}.Row]]]",
    ]
    for column in table.columns:
        if (
            column.query_type is None
            or column.storage not in constructors
            or not column.name.isidentifier()
            or keyword.iskeyword(column.name)
        ):
            msg = f"{table.name}.{column.name}: query contract requires an explicit codec/name adapter"
            raise PackageError(msg)
        lines.append(
            f"    {column.name}: {backend}.Col[{column.query_type}] = "
            f"{backend}.{constructors[column.storage]}(nullable={column.nullable!r})"
        )
    return "\n".join(lines) + "\n"


def _add_column(table: TableState, column: ColumnState) -> TableState:
    if not column.nullable or any(
        word in column.definition.upper()
        for word in ("PRIMARY", "UNIQUE", "DEFAULT", "REFERENCES", "CHECK", "GENERATED")
    ):
        msg = "only unconstrained nullable additions are supported in this prototype"
        raise PackageError(msg)
    if column.name in {existing.name for existing in table.columns}:
        msg = f"column {column.name!r} already exists"
        raise PackageError(msg)
    prefix = f"CREATE TABLE {table.quoted_name} (" + ", ".join(
        existing.definition for existing in table.columns
    )
    if not table.sql.startswith(prefix):
        msg = "table construction and column state disagree"
        raise PackageError(msg)
    return table.model_copy(
        update={
            "sql": prefix + ", " + column.definition + table.sql[len(prefix) :],
            "columns": (*table.columns, column),
        }
    )


_RESERVED = frozenset({"snekql_migrations", "snekql_experimental_migrations"})


def _validate_draft(draft: Draft) -> None:
    if any(
        table.name.casefold() in _RESERVED
        for table in (*draft.before.tables, *draft.target.tables)
    ):
        msg = "runner metadata cannot be managed by application migrations"
        raise PackageError(msg)
    if not draft.revision.strip() or draft.unresolved:
        msg = f"unresolved migration {draft.revision!r}: {draft.unresolved}"
        raise PackageError(msg)
    if draft.before.backend != draft.target.backend:
        msg = "a migration cannot change backend"
        raise PackageError(msg)


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
    def __init__(self, backend: Backend) -> None:
        self.backend = backend
        self.statements: list[str | None] = []
        self.bindings: list[tuple[Parameter, ...]] = []
        self.transactional: list[bool] = []
        self.contractions: list[Contraction | None] = []
        self.pending: Contraction | None = None

    def emit(
        self,
        sql: str,
        params: tuple[Parameter, ...] = (),
        *,
        transactional: bool = False,
    ) -> None:
        self.flush()
        self.statements.append(sql)
        self.bindings.append(params)
        self.transactional.append(transactional)
        self.contractions.append(None)

    def contract(
        self,
        before: TableState,
        after: TableState,
        operation: RequireNotNull | DropColumn,
    ) -> None:
        if self.pending is not None and self.pending.before.name != before.name:
            self.flush()
        pending = self.pending or Contraction(before=before, after=after)
        self.pending = pending.model_copy(
            update={
                "after": after,
                "required": (*pending.required, operation.column_name)
                if isinstance(operation, RequireNotNull)
                else pending.required,
                "dropped": (*pending.dropped, operation.column_name)
                if isinstance(operation, DropColumn)
                else pending.dropped,
            }
        )

    def flush(self) -> None:
        pending = self.pending
        if pending is None:
            return
        clauses = [
            "MODIFY COLUMN "
            + next(c.definition for c in pending.after.columns if c.name == name)
            for name in pending.required
        ]
        clauses.extend(
            "DROP COLUMN `" + name.replace("`", "``") + "`" for name in pending.dropped
        )
        self.statements.append(
            None
            if self.backend == "sqlite"
            else f"ALTER TABLE {pending.before.quoted_name} " + ", ".join(clauses)
        )
        self.bindings.append(())
        self.transactional.append(False)
        self.contractions.append(pending)
        self.pending = None


def _emit_creation(
    table: TableState, tables: dict[str, TableState], emission: _Emission
) -> None:
    if table.name in tables:
        msg = f"table {table.name!r} already exists in managed state"
        raise PackageError(msg)
    tables[table.name] = table
    for sql in (table.sql, *table.indexes):
        emission.emit(sql)


def compile(draft: Draft) -> Package:  # noqa: A001 - deliberate authoring verb
    """Validate the route and freeze SQL; never import current application models."""
    _validate_draft(draft)
    tables = {table.name: table for table in draft.before.tables}
    emission = _Emission(draft.target.backend)
    checkpoints: dict[str, str] = {}
    for operation in draft.operations:
        if isinstance(operation, RequireNotNull | DropColumn):
            before = tables[operation.table_name]
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
        table = operation.table
        _emit_creation(table, tables, emission)
    if tables != {table.name: table for table in draft.target.tables}:
        msg = "operation endpoint does not match the recorded target state"
        raise PackageError(msg)
    emission.flush()
    payload = {
        "version": 2,
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
        draft=draft,
        statements=tuple(emission.statements),
        bindings=tuple(emission.bindings),
        transactional=tuple(emission.transactional),
        contractions=tuple(emission.contractions),
        digest=_digest(payload),
    )


# Lazy re-export avoids importing optional drivers or creating a connection.

__all__ = [
    "AddColumn",
    "Checkpoint",
    "ColumnState",
    "Contraction",
    "CreateTable",
    "DataChange",
    "Draft",
    "DropColumn",
    "Package",
    "PackageError",
    "Prepared",
    "Progress",
    "Recovery",
    "RequireNotNull",
    "State",
    "TableState",
    "Target",
    "compile",
    "connect",
    "contract_digest",
    "contract_source",
    "generate",
]
