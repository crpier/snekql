"""Experimental recorded-state migration authoring and frozen execution packages.

Formats 2/3/4/5/6/7/8 are prototypes, not a supported long-term interchange contract.
Formats 3/4 add defaults/relaxation; formats 5/6 add index creation/removal;
format 7 adds named CHECKs and format 8 removes them. Older routes retain their existing formats.
Models are consulted only during generation; loading packages imports none.
"""

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from itertools import chain
from types import UnionType
from typing import Any, Literal, Self, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field

from snekql._scaffold import require_scaffold_models
from snekql._schema_compile import compile_create_index_sql, compile_create_table_sql
from snekql._schema_plan import build_schema_plan
from snekql.errors import SchemaError, SnekqlError
from snekql.experimental._migration_package import read_package
from snekql.experimental._migration_sql import (
    ascii_lower,
    column_name,
    nullable_definition,
    references,
    required_definition,
    split_table,
    tokens,
    without_default,
)
from snekql.model import Table
from snekql.query import Write
from snekql.storage import _extract_logical_type, _resolve_model_hint
lazy from snekql.experimental._migration_checks import (
    add_check,
    check_additions,
    check_removals,
    drop_check,
)
lazy from snekql.experimental._migration_collation import (
    validate_collation_claims,
    validate_column_collation,
)
lazy from snekql.experimental._migration_contract import (
    historical_annotation,
    historical_field_name,
    historical_primitive_matches,
)
lazy from snekql.experimental._migration_default_claims import (
    validate_column_default,
    validate_default_claims,
)
lazy from snekql.experimental._migration_identity import (
    validate_column_identity,
    validate_identity_claims,
)
lazy from snekql.experimental._migration_indexes import (
    add_index,
    drop_index,
    index_removals,
)
lazy from snekql.experimental._migration_keys import (
    validate_column_inline_key,
    validate_inline_key_claims,
)
lazy from snekql.experimental._migration_mariadb import mariadb_default_parts
lazy from snekql.experimental._migration_not_null import (
    validate_column_not_null,
    validate_not_null_claims,
)
lazy from snekql.experimental._migration_nullability import (
    validate_column_nullability,
    validate_key_nullability_claims,
    validate_nullability_claims,
)
lazy from snekql.experimental._migration_storage import (
    validate_column_storage,
    validate_storage_claims,
)
lazy from snekql.experimental._migration_target import (
    Prepared,
    Progress,
    Reconciliation,
    Recovery,
    Target,
    connect,
)
lazy from snekql.experimental._migration_unique import (
    validate_column_unique,
    validate_unique_claims,
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


class CreateIndex(_Value):
    """Create a new named whole-column index on a managed table, without adoption."""

    kind: Literal["create_index"] = "create_index"
    table_name: str
    sql: str


class DropIndex(_Value):
    """Explicitly remove one named managed secondary index, including uniqueness."""

    kind: Literal["drop_index"] = "drop_index"
    table_name: str
    index_name: str


class AddCheck(_Value):
    """Add a named bounded table CHECK; existing rows must satisfy it."""

    kind: Literal["add_check"] = "add_check"
    table_name: str
    definition: str


class DropCheck(_Value):
    """Explicitly remove one recorded named table CHECK, never an implicit constraint."""

    kind: Literal["drop_check"] = "drop_check"
    table_name: str
    check_name: str


class AdoptTable(_Value):
    """Claim a matching existing SQLite table without creating or changing it."""

    kind: Literal["adopt_table"] = "adopt_table"
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


class AllowNull(_Value):
    """Relax an ordinary managed NOT NULL column without changing its values."""

    kind: Literal["allow_null"] = "allow_null"
    table_name: str
    column_name: str


class ChangeDefault(_Value):
    """Change only a column's default; existing values are preserved."""

    kind: Literal["change_default"] = "change_default"
    table_name: str
    column: ColumnState

    @property
    def column_name(self) -> str:
        """Identify the managed column whose declaration supplies the new default."""
        return self.column.name


class DropColumn(_Value):
    """Explicit authorization to remove one managed column, not its dependencies."""

    kind: Literal["drop_column"] = "drop_column"
    table_name: str
    column_name: str


class RelinquishTable(_Value):
    """Stop managing one table without changing its physical schema or rows."""

    kind: Literal["relinquish_table"] = "relinquish_table"
    table_name: str


class Contraction(_Value):
    """A grouped table transition requiring backend-aware execution planning."""

    before: TableState
    after: TableState
    required: tuple[str, ...] = ()
    dropped: tuple[str, ...] = ()
    defaults: tuple[str, ...] = Field(default=(), exclude_if=lambda value: not value)
    relaxed: tuple[str, ...] = Field(default=(), exclude_if=lambda value: not value)
    removed_checks: tuple[str, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    added_checks: tuple[str, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )


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
        CreateTable
        | AdoptTable
        | AddCheck
        | DropCheck
        | CreateIndex
        | DropIndex
        | AddColumn
        | RequireNotNull
        | AllowNull
        | ChangeDefault
        | DropColumn
        | RelinquishTable
        | Checkpoint
        | DataChange,
        ...,
    ]
    unresolved: tuple[str, ...] = ()

    def then(
        self,
        *operations: CreateTable
        | AdoptTable
        | AddCheck
        | DropCheck
        | CreateIndex
        | DropIndex
        | AddColumn
        | RequireNotNull
        | AllowNull
        | ChangeDefault
        | DropColumn
        | RelinquishTable
        | Checkpoint
        | DataChange,
    ) -> Self:
        """Append typed authoring steps while retaining the original immutable draft."""
        return self.model_copy(update={"operations": (*self.operations, *operations)})

    def adopt(self, *table_names: str) -> Self:
        """Replace named proposed creations with explicit, target-verified adoption."""
        if len(set(table_names)) != len(table_names) or any(
            sum(
                isinstance(operation, CreateTable) and operation.table.name == name
                for operation in self.operations
            )
            != 1
            for name in table_names
        ):
            msg = "adoption requires distinct names with exactly one proposed creation each"
            raise PackageError(msg)
        return self.model_copy(
            update={
                "operations": tuple(
                    AdoptTable(table=operation.table)
                    if isinstance(operation, CreateTable)
                    and operation.table.name in table_names
                    else operation
                    for operation in self.operations
                )
            }
        )

    def resolve(
        self, *removals: DropColumn | DropIndex | DropCheck | RelinquishTable
    ) -> Self:
        """Authorize named removals; index/CHECK removals precede dependent alterations."""
        unresolved = list(self.unresolved)
        for removal in removals:
            decision = (
                _relinquish_decision(removal.table_name)
                if isinstance(removal, RelinquishTable)
                else _index_decision(removal.table_name, removal.index_name)
                if isinstance(removal, DropIndex)
                else _check_decision(removal.table_name, removal.check_name)
                if isinstance(removal, DropCheck)
                else _drop_decision(removal.table_name, removal.column_name)
            )
            if decision not in unresolved:
                msg = f"no pending removal decision: {decision}"
                raise PackageError(msg)
            unresolved.remove(decision)
        return self.model_copy(
            update={
                "operations": (
                    *(op for op in removals if isinstance(op, DropIndex | DropCheck)),
                    *self.operations,
                    *(
                        op
                        for op in removals
                        if not isinstance(op, DropIndex | DropCheck)
                    ),
                ),
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

    version: Literal[2, 3, 4, 5, 6, 7, 8] = 2
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
            package = cls.model_validate(read_package(text))
        except ValueError as error:
            msg = f"invalid or unsupported execution package format: {error}"
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
    defaulted_additions: Literal["leave_null"] | None = None,
) -> Draft:
    """Draft changes against recorded intent, never against a developer database.

    Unsupported alterations and ownership removal remain explicit unresolved
    decisions. Supported routes include creation, nullable additions, typed
    backfills, contraction, default alterations, explicit whole-table relinquishment,
    and SQLite adoption. Opting into ``defaulted_additions="leave_null"`` adds
    nullable columns without defaults, then sets defaults for future writes. It
    never infers an existing-row backfill or permits required additions.
    """
    if defaulted_additions not in (None, "leave_null"):
        msg = "unsupported defaulted-addition policy"
        raise PackageError(msg)
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
    unresolved = [_relinquish_decision(name) for name in old.keys() - desired.keys()]
    operations: list[
        CreateTable
        | AddCheck
        | DropCheck
        | CreateIndex
        | DropIndex
        | AddColumn
        | RequireNotNull
        | AllowNull
        | ChangeDefault
    ] = []
    for table in tables:
        if table.name not in old:
            operations.append(CreateTable(table=table))
        elif old[table.name] != table:
            try:
                current, removed_indexes = index_removals(
                    old[table.name], table, backend
                )
                current, removed_checks = check_removals(current, table, backend)
                candidates, removed = _changes(
                    current, table, backend, defaulted_additions
                )
            except PackageError:
                unresolved.append(
                    f"{table.name}: alteration requires a supported structured operation"
                )
            else:
                operations.extend(candidates)
                unresolved.extend(
                    _check_decision(table.name, name) for name in removed_checks
                )
                unresolved.extend(
                    _index_decision(table.name, name) for name in removed_indexes
                )
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
    current: TableState,
    desired: TableState,
    backend: Backend,
    defaulted_additions: Literal["leave_null"] | None,
) -> tuple[
    list[
        AddColumn | RequireNotNull | AllowNull | ChangeDefault | CreateIndex | AddCheck
    ],
    list[str],
]:
    candidates: list[
        AddColumn | RequireNotNull | AllowNull | ChangeDefault | CreateIndex | AddCheck
    ] = []
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
            initial = _addition_column(column, backend, defaulted_additions)
            change = AddColumn(table_name=desired.name, column=initial)
            current = _add_column(current, initial)
            candidates.append(change)
            if initial != column:
                default_change = ChangeDefault(table_name=desired.name, column=column)
                current = _contract_table(current, default_change, backend)
                candidates.append(default_change)
        elif existing != column:
            default_change = ChangeDefault(table_name=desired.name, column=column)
            try:
                revised = _contract_table(current, default_change, backend)
            except PackageError:
                change = (
                    AllowNull(table_name=desired.name, column_name=column.name)
                    if not existing.nullable and column.nullable
                    else RequireNotNull(
                        table_name=desired.name, column_name=column.name
                    )
                )
                current = _contract_table(current, change, backend)
                candidates.append(change)
                required_column = next(
                    item for item in current.columns if item.name == column.name
                )
                if required_column != column:
                    current = _contract_table(current, default_change, backend)
                    candidates.append(default_change)
            else:
                current = revised
                candidates.append(default_change)
    for name in removed:
        current = _contract_table(
            current, DropColumn(table_name=desired.name, column_name=name), backend
        )
    current, indexes = _index_additions(current, desired, backend)
    candidates.extend(indexes)
    current, checks = check_additions(current, desired, backend)
    candidates.extend(
        AddCheck(table_name=desired.name, definition=definition)
        for definition in checks
    )
    if current != desired:
        msg = "alteration is not representable by supported operations"
        raise PackageError(msg)
    return candidates, removed


def _index_additions(
    current: TableState, desired: TableState, backend: Backend
) -> tuple[TableState, list[CreateIndex]]:
    additions = []
    for sql in desired.indexes:
        if sql not in current.indexes:
            current = add_index(current, sql, backend)
            additions.append(CreateIndex(table_name=desired.name, sql=sql))
    return current, additions


def _addition_column(
    column: ColumnState, backend: Backend, policy: Literal["leave_null"] | None
) -> ColumnState:
    if policy is None:
        return column
    try:
        definition = (
            mariadb_default_parts(column.definition)[0]
            if backend == "mariadb"
            else without_default(column.definition)
        )
    except SchemaError as error:
        raise PackageError(str(error)) from error
    return column.model_copy(update={"definition": definition})


def _relinquish_decision(table: str) -> str:
    return f"{table}: deletion versus relinquishing ownership requires a decision"


def _managed_table(tables: dict[str, TableState], name: str) -> TableState:
    try:
        return tables[name]
    except KeyError as error:
        msg = f"table {name!r} is not managed at this point in the route"
        raise PackageError(msg) from error


def _relinquish(tables: dict[str, TableState], name: str) -> None:
    if name not in tables:
        msg = f"cannot relinquish unmanaged table {name!r}"
        raise PackageError(msg)
    del tables[name]


def _check_decision(table: str, name: str) -> str:
    return f"{table}: explicitly authorize removal of CHECK {name!r}"


def _index_decision(table: str, name: str) -> str:
    """Name an unresolved destructive index decision without authorizing it."""
    return f"{table}: explicitly authorize removal of index {name!r}"


def _drop_decision(table: str, column: str) -> str:
    return f"{table}.{column}: explicit DropColumn required"


def _contract_table(
    table: TableState,
    operation: RequireNotNull | AllowNull | DropColumn | ChangeDefault,
    backend: Backend,
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
    if isinstance(operation, ChangeDefault):
        replacement = _changed_default_column(column, operation.column, backend)
        columns = tuple(
            replacement if item == column else item for item in table.columns
        )
    elif isinstance(operation, AllowNull):
        replacement = _relaxed_column(column, tail, backend)
        columns = tuple(
            replacement if item == column else item for item in table.columns
        )
    elif isinstance(operation, DropColumn):
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


def _relaxed_column(column: ColumnState, tail: str, backend: Backend) -> ColumnState:
    """Derive only nullability/type changes, refusing coupled table constraints."""
    if column.nullable or references(tail, {column.name}, mysql=backend == "mariadb"):
        msg = (
            "AllowNull requires a required column without table-constraint dependencies"
        )
        raise PackageError(msg)
    try:
        definition = nullable_definition(column.definition, mysql=backend == "mariadb")
    except SchemaError as error:
        raise PackageError(str(error)) from error
    return column.model_copy(
        update={
            "nullable": True,
            "definition": definition,
            "query_type": column.query_type + " | None" if column.query_type else None,
        }
    )


def _changed_default_column(
    column: ColumnState, replacement: ColumnState, backend: Backend
) -> ColumnState:
    """Keep all non-default declaration text and recorded column facts unchanged."""
    try:
        if backend == "mariadb":
            unchanged = (
                mariadb_default_parts(column.definition)[0]
                == mariadb_default_parts(replacement.definition)[0]
            )
        else:
            unchanged = without_default(column.definition) == without_default(
                replacement.definition
            )
    except SchemaError as error:
        raise PackageError(str(error)) from error
    if (
        not unchanged
        or column == replacement
        or column.model_copy(update={"definition": replacement.definition})
        != replacement
    ):
        msg = "ChangeDefault must change only the default of an existing column"
        raise PackageError(msg)
    return replacement


def _query_type(model: type[Table[Any]], name: str) -> str | None:
    logical = _extract_logical_type(_resolve_model_hint(model, name), name)
    arguments = get_args(logical)
    if arguments and get_origin(logical) is not UnionType:
        return None
    types = arguments or (logical,)
    supported: dict[object, str] = {
        int: "int",
        str: "str",
        float: "float",
        bytes: "bytes",
        bool: "bool",
        type(None): "None",
    }
    if any(not any(value is scalar for scalar in supported) for value in types):
        return None
    return " | ".join(supported[value] for value in types)


def _auxiliary_change(
    table: TableState,
    operation: AddCheck | DropCheck | CreateIndex | DropIndex,
    backend: Backend,
) -> TableState:
    """Project non-column structural operations at historical query checkpoints."""
    if isinstance(operation, DropCheck):
        return drop_check(table, operation.check_name, backend)
    if isinstance(operation, AddCheck):
        return add_check(table, operation.definition, backend)
    if isinstance(operation, DropIndex):
        return drop_index(table, operation.index_name, backend)
    return add_index(table, operation.sql, backend)


def contract_source(draft: Draft, *, point: str, table: str) -> str:
    """Emit a standalone static query model at a named draft checkpoint.

    Only built-in scalar contracts are supported; custom codecs never silently
    degrade to their physical storage types. No application code is imported.
    """
    tables = {item.name: item for item in draft.before.tables}
    for operation in draft.operations:
        if isinstance(operation, RelinquishTable):
            _relinquish(tables, operation.table_name)
        elif isinstance(operation, CreateTable | AdoptTable):
            tables[operation.table.name] = operation.table
        elif isinstance(operation, AddCheck | DropCheck | CreateIndex | DropIndex):
            tables[operation.table_name] = _auxiliary_change(
                _managed_table(tables, operation.table_name),
                operation,
                draft.target.backend,
            )
        elif isinstance(operation, AddColumn):
            tables[operation.table_name] = _add_column(
                _managed_table(tables, operation.table_name), operation.column
            )
        elif isinstance(
            operation, RequireNotNull | AllowNull | DropColumn | ChangeDefault
        ):
            tables[operation.table_name] = _contract_table(
                _managed_table(tables, operation.table_name),
                operation,
                draft.target.backend,
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
        if isinstance(operation, RelinquishTable):
            _relinquish(tables, operation.table_name)
        elif isinstance(operation, CreateTable | AdoptTable):
            tables[operation.table.name] = operation.table
        elif isinstance(operation, AddCheck | DropCheck | CreateIndex | DropIndex):
            tables[operation.table_name] = _auxiliary_change(
                _managed_table(tables, operation.table_name),
                operation,
                draft.target.backend,
            )
        elif isinstance(operation, AddColumn):
            tables[operation.table_name] = _add_column(
                _managed_table(tables, operation.table_name), operation.column
            )
        elif isinstance(
            operation, RequireNotNull | AllowNull | DropColumn | ChangeDefault
        ):
            tables[operation.table_name] = _contract_table(
                _managed_table(tables, operation.table_name),
                operation,
                draft.target.backend,
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
        annotation = historical_annotation(column.query_type)
        if (
            annotation is None
            or column.storage not in constructors
            or not historical_primitive_matches(column, backend)
            or not historical_field_name(column.name, backend)
        ):
            msg = f"{table.name}.{column.name}: query contract requires an explicit codec/name adapter"
            raise PackageError(msg)
        lines.append(
            f"    {column.name}: {backend}.Col[{annotation}] = "
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


def _validate_column_identifier(column: ColumnState, backend: Backend) -> None:
    """Bind independently recorded names to executable column definitions."""
    try:
        stream = tokens(column.definition, mysql=backend == "mariadb")
        if (
            not column.name
            or not stream
            or stream[0].kind not in {"identifier", "word"}
            or column_name(column.definition, mysql=backend == "mariadb") != column.name
        ):
            msg = "column identifier claim must match its SQL definition"
            raise PackageError(msg)
    except SchemaError as error:
        msg = f"column identifier claim is invalid: {error}"
        raise PackageError(msg) from error


def _unique_identifiers(names: Iterable[str]) -> None:
    seen: set[str] = set()
    for name in names:
        folded = ascii_lower(name)
        if not name or folded in seen:
            msg = "ambiguous recorded identifiers require an explicit adapter"
            raise PackageError(msg)
        seen.add(folded)


def _validate_column_coverage(table: TableState, backend: Backend) -> None:
    """Prove positive managed-column presence without claiming unmanaged extras."""
    mysql = backend == "mariadb"
    names: Counter[str] = Counter()
    try:
        for part in split_table(table.sql, mysql=mysql)[1]:
            stream = tokens(part, mysql=mysql)
            if stream and stream[0].kind in {"identifier", "word"}:
                name = column_name(part, mysql=mysql)
                if name is not None:
                    names[ascii_lower(name)] += 1
    except SchemaError as error:
        msg = f"managed column construction cannot be verified: {error}"
        raise PackageError(msg) from error
    for column in table.columns:
        if names[ascii_lower(column.name)] != 1:
            msg = f"managed column construction requires exactly one declaration for {table.name!r}.{column.name!r}"
            raise PackageError(msg)


_CREATE_TABLE_HEADER_TOKENS = 4


def _validate_construction_header(table: TableState, backend: Backend) -> None:
    """Admit only unqualified ordinary CREATE TABLE for the recorded exact owner."""
    try:
        stream = tokens(table.sql, mysql=backend == "mariadb")
    except SchemaError as error:
        msg = f"unsupported table construction header: {error}"
        raise PackageError(msg) from error
    if (
        len(stream) < _CREATE_TABLE_HEADER_TOKENS
        or tuple((t.kind, ascii_lower(t.value)) for t in stream[:2])
        != (("word", "create"), ("word", "table"))
        or stream[2].kind not in {"word", "identifier"}
        or stream[2].value != table.name
        or (stream[3].kind, stream[3].value) != ("punct", "(")
    ):
        msg = "table construction header must be an unqualified ordinary CREATE TABLE naming its recorded owner"
        raise PackageError(msg)
    end = 0
    for token in stream[:_CREATE_TABLE_HEADER_TOKENS]:
        if table.sql[end : token.start].strip():
            msg = "table construction header comments require an explicit adapter"
            raise PackageError(msg)
        end = token.end


def _validate_table_identifiers(table: TableState, backend: Backend) -> None:
    """Bind identifiers without claiming SQL equivalence or codec correctness."""
    try:
        identifier = tokens(table.quoted_name, mysql=backend == "mariadb")
    except SchemaError as error:
        msg = f"table identifier claim is invalid: {error}"
        raise PackageError(msg) from error
    if (
        not table.name
        or len(identifier) != 1
        or identifier[0].kind != "identifier"
        or identifier[0].value != table.name
        or table.quoted_name
        != table.quoted_name[identifier[0].start : identifier[0].end]
    ):
        msg = "table identifier claim must match its single quoted SQL name"
        raise PackageError(msg)
    _unique_identifiers(column.name for column in table.columns)
    for column in table.columns:
        _validate_column_identifier(column, backend)


def _validate_draft(draft: Draft) -> None:
    for state in (draft.before, draft.target):
        _unique_identifiers(table.name for table in state.tables)
    for table in chain(
        draft.before.tables,
        draft.target.tables,
        (
            op.table
            for op in draft.operations
            if isinstance(op, CreateTable | AdoptTable)
        ),
    ):
        _validate_table_identifiers(table, draft.target.backend)
        _validate_construction_header(table, draft.target.backend)
        _validate_column_coverage(table, draft.target.backend)
        validate_nullability_claims(table, draft.target.backend)
        validate_storage_claims(table, draft.target.backend)
        validate_collation_claims(table, draft.target.backend)
        validate_default_claims(table, draft.target.backend)
        validate_inline_key_claims(table, draft.target.backend)
        validate_key_nullability_claims(table, draft.target.backend)
        validate_unique_claims(table, draft.target.backend)
        validate_not_null_claims(table, draft.target.backend)
        validate_identity_claims(table, draft.target.backend)
    for op in draft.operations:
        if isinstance(op, AddColumn | ChangeDefault):
            _validate_column_identifier(op.column, draft.target.backend)
            validate_column_nullability(op.column, draft.target.backend)
            validate_column_storage(op.column, draft.target.backend)
            validate_column_collation(op.column, draft.target.backend)
            validate_column_default(op.column, draft.target.backend)
            validate_column_inline_key(op.column, draft.target.backend)
            validate_column_unique(op.column, draft.target.backend)
            validate_column_not_null(op.column, draft.target.backend)
            validate_column_identity(op.column, draft.target.backend)
    if any(
        table.name.casefold() in _RESERVED
        for table in (
            *draft.before.tables,
            *draft.target.tables,
            *(
                operation.table
                for operation in draft.operations
                if isinstance(operation, CreateTable | AdoptTable)
            ),
        )
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


def compile(draft: Draft) -> Package:  # noqa: A001 - deliberate authoring verb
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


# Lazy re-export avoids importing optional drivers or creating a connection.

__all__ = [
    "AddCheck",
    "AddColumn",
    "AdoptTable",
    "AllowNull",
    "ChangeDefault",
    "Checkpoint",
    "ColumnState",
    "Contraction",
    "CreateIndex",
    "CreateTable",
    "DataChange",
    "Draft",
    "DropCheck",
    "DropColumn",
    "DropIndex",
    "Package",
    "PackageError",
    "Prepared",
    "Progress",
    "Reconciliation",
    "Recovery",
    "RelinquishTable",
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
