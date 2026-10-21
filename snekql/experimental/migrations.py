"""Experimental recorded-state migration authoring and frozen execution packages.

Format 1 is a prototype, not a supported long-term interchange contract. Models
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
from snekql.model import Table
from snekql.query import Write
from snekql.storage import _extract_logical_type, _resolve_model_hint
lazy from snekql.experimental._migration_target import (
    Prepared,
    Progress,
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
    operations: tuple[CreateTable | AddColumn | Checkpoint | DataChange, ...]
    unresolved: tuple[str, ...] = ()

    def then(
        self, *operations: CreateTable | AddColumn | Checkpoint | DataChange
    ) -> Self:
        """Append typed authoring steps while retaining the original immutable draft."""
        return self.model_copy(update={"operations": (*self.operations, *operations)})


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


class Package(_Value):
    """Frozen execution plus historical contracts, with a content-integrity digest.

    Digests detect changes, not malicious publishers. Load only trusted packages.
    """

    version: Literal[1] = 1
    draft: Draft
    statements: tuple[str, ...]
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
    decisions. This slice supports creation, nullable additions and explicit typed backfills.
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
    operations: list[CreateTable | AddColumn] = []
    for table in tables:
        if table.name not in old:
            operations.append(CreateTable(table=table))
        elif old[table.name] != table:
            current = old[table.name]
            additions = table.columns[len(current.columns) :]
            candidates = [
                AddColumn(table_name=table.name, column=column) for column in additions
            ]
            try:
                for operation in candidates:
                    current = _add_column(current, operation.column)
            except PackageError:
                current = old[table.name]
            if current == table:
                operations.extend(candidates)
            else:
                unresolved.append(
                    f"{table.name}: alteration requires a supported structured operation"
                )
    return Draft(
        revision=revision,
        predecessor=previous.digest if previous else None,
        before=before,
        target=State(backend=backend, tables=tables),
        operations=tuple(operations),
        unresolved=tuple(sorted(unresolved)),
    )


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


def compile(draft: Draft) -> Package:  # noqa: A001 - deliberate authoring verb
    """Validate the route and freeze SQL; never import current application models."""
    _validate_draft(draft)
    tables = {table.name: table for table in draft.before.tables}
    statements: list[str] = []
    bindings: list[tuple[Parameter, ...]] = []
    transactional: list[bool] = []
    checkpoints: dict[str, str] = {}
    for operation in draft.operations:
        if isinstance(operation, Checkpoint):
            if not operation.name or operation.name in checkpoints:
                msg = "checkpoint names must be nonempty and unique"
                raise PackageError(msg)
            checkpoints[operation.name] = _state_digest(draft.target.backend, tables)
            continue
        if isinstance(operation, DataChange):
            _validate_data_change(operation, draft, checkpoints, tables)
            statements.append(operation.sql)
            bindings.append(operation.params)
            transactional.append(True)
            continue
        if isinstance(operation, AddColumn):
            if operation.table_name not in tables:
                msg = "cannot add column to an unmanaged table"
                raise PackageError(msg)
            current = tables[operation.table_name]
            tables[operation.table_name] = _add_column(current, operation.column)
            statements.append(
                f"ALTER TABLE {current.quoted_name} ADD COLUMN {operation.column.definition}"
            )
            bindings.append(())
            transactional.append(False)
            continue
        table = operation.table
        if table.name in tables:
            msg = f"table {table.name!r} already managed"
            raise PackageError(msg)
        tables[table.name] = table
        statements.extend((table.sql, *table.indexes))
        bindings.extend(() for _ in (table.sql, *table.indexes))
        transactional.extend(False for _ in (table.sql, *table.indexes))
    if tables != {table.name: table for table in draft.target.tables}:
        msg = "operation endpoint does not match the recorded target state"
        raise PackageError(msg)
    payload = {
        "version": 1,
        "draft": draft.model_dump(mode="json"),
        "statements": statements,
        "bindings": bindings,
        "transactional": transactional,
    }
    return Package(
        draft=draft,
        statements=tuple(statements),
        bindings=tuple(bindings),
        transactional=tuple(transactional),
        digest=_digest(payload),
    )


# Lazy re-export avoids importing optional drivers or creating a connection.

__all__ = [
    "AddColumn",
    "Checkpoint",
    "ColumnState",
    "CreateTable",
    "DataChange",
    "Draft",
    "Package",
    "PackageError",
    "Prepared",
    "Progress",
    "State",
    "TableState",
    "Target",
    "compile",
    "connect",
    "contract_digest",
    "contract_source",
    "generate",
]
