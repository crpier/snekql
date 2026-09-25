"""Throwaway dual-class relations and a bounded SQLite query experiment.

No production compiler replacement. Column declarations remain in records.py.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import UnionType
from typing import (
    Annotated,
    Any,
    Generic,
    LiteralString,
    Protocol,
    TypeVar,
    TypeVarTuple,
    cast,
    get_args,
    get_origin,
    overload,
)

from aiosqlite import Connection

from scratchpad.dual_features.models import ReadRow
from scratchpad.dual_features.records import Assignment, Column, Insert, ModelError

Owner = TypeVar("Owner", bound=ReadRow)
Target = TypeVar("Target", bound=ReadRow)
Value = TypeVar("Value")
Scope_co = TypeVar("Scope_co", covariant=True)
InvariantScope = TypeVar("InvariantScope")


def _quote(name: str) -> str:
    """Quote a SQLite identifier, escaping embedded double quotes.

    This is for table, alias, and column names. Data values use parameters."""

    return '"' + name.replace('"', '""') + '"'


def _domain(annotation: object) -> object:
    """Compare the tested logical domains independently of scalar nullability.

    Strip Annotated metadata and a single optional None member. This deliberately
    omits full type-alias resolution, constraint implication, and codec/storage
    compatibility; matching these domains does not establish a valid schema."""

    if get_origin(annotation) is Annotated:
        return _domain(get_args(annotation)[0])
    if get_origin(annotation) is UnionType:
        members = tuple(item for item in get_args(annotation) if item is not type(None))
        if len(members) == 1:
            return _domain(members[0])
    return annotation


@dataclass(frozen=True)
class Reference(Generic[Owner, Target, Value]):
    """A checked scalar column pair with join metadata and optional FK DDL."""

    source: Column[Owner, Value] | Column[Owner, Value | None]
    target: Column[Target, Value]
    enforced: bool = True

    def and_[OtherValue](
        self, other: Reference[Owner, Target, OtherValue]
    ) -> CompositeReference[Owner, Target]:
        """Combine this pair with another pair from the same two tables."""

        return CompositeReference[Owner, Target]((self,)).and_(other)

    def on[SourceScope, TargetScope](
        self, source: Source[SourceScope, Owner], target: Source[TargetScope, Target]
    ) -> Predicate[SourceScope | TargetScope]:
        """Bind both ends to concrete source identities and compare their columns."""

        if (
            source.row_type is not self.source.owner
            or target.row_type is not self.target.owner
        ):
            message = "Relationship was bound to another table"
            raise ModelError(message)
        source_name = _quote(source.name or source.row_type.table_name)
        target_name = _quote(target.name or target.row_type.table_name)
        return Predicate[SourceScope | TargetScope](
            f"{source_name}.{_quote(self.source.name)} = {target_name}.{_quote(self.target.name)}",
            frozenset({source.token, target.token}),
        )

    def ddl(self) -> str:
        """Emit an FK constraint fragment, or an empty string for a soft reference."""

        if not self.enforced:
            return ""
        return f"FOREIGN KEY ({_quote(self.source.name)}) REFERENCES {_quote(self.target.owner.table_name)} ({_quote(self.target.name)})"


@dataclass(frozen=True)
class ReferenceFrom(Generic[Owner, Value]):
    """The source half of a staged relationship, awaiting a target column."""

    source: Column[Owner, Value] | Column[Owner, Value | None]

    def to[Target: ReadRow](
        self, target: Column[Target, Value], *, enforced: bool = True
    ) -> Reference[Owner, Target, Value]:
        """Complete the pair after comparing its tested logical domains.

        Disabling enforcement suppresses DDL only; it retains typed join metadata.
        This check does not establish target uniqueness or physical compatibility."""

        source_domain = _domain(self.source.owner.specs[self.source.name].logical_type)
        target_domain = _domain(target.owner.specs[target.name].logical_type)
        if source_domain != target_domain:
            message = "Foreign-key logical domains differ"
            raise ModelError(message)
        return Reference(self.source, target, enforced)


def reference[Owner: ReadRow, Value](
    source: Column[Owner, Value],
) -> ReferenceFrom[Owner, Value]:
    """Start a staged relationship from a nonnullable column.

    Finish with `.to(target_column)`, which checks the logical value domain and
    retains both table types. Use `nullable_reference` for an optional source,
    or `relationship(source, target)` to avoid spelling source nullability.
    Construction performs no SQL and installs no database constraint.

    ```python
    from scratchpad.dual_features.models import Account, Entry

    edge = reference(Entry.note).to(Account.code, enforced=False)
    ```"""

    return ReferenceFrom[Owner, Value](source)


def nullable_reference[Owner: ReadRow, Value](
    source: Column[Owner, Value | None],
) -> ReferenceFrom[Owner, Value]:
    """Start a staged relationship from an optional column.

    `.to(...)` expects the corresponding nonnullable target value type. None is
    allowed in the source row without making the referenced row type optional.
    Use `relationship` for nullable targets or a single-call declaration.

    ```python
    from scratchpad.dual_features.models import Account, Entry

    edge = nullable_reference(Entry.account_id).to(Account.id)
    ```"""

    return ReferenceFrom[Owner, Value](source)


ReadyState = TypeVar("ReadyState")
Values = TypeVarTuple("Values")
Role = TypeVar("Role")

type Token = tuple[type[ReadRow], type[object] | str | None, bool, str]


class Ready:
    """Explicit row scope was supplied."""


class Unscoped:
    """Not executable yet."""


class Alias(Generic[Owner, Role]):
    """Nominal scope, separate from the returned row class."""


class Outer[Inner]:
    """A nullable SQL source has a distinct scope from its nonnullable view."""


@dataclass(frozen=True)
class Predicate(Generic[Scope_co]):
    """A SQL condition carrying every referenced source and bound parameter."""

    sql: str
    owners: frozenset[Token]
    parameters: tuple[object, ...] = ()

    def __predicate__(self) -> Predicate[Scope_co]:
        """Share a join-condition contract with predeclared relationships."""
        return self

    def __and__[OtherScope](
        self, other: Predicate[OtherScope]
    ) -> Predicate[Scope_co | OtherScope]:
        # The runtime owner set is the union; the scope coordinate is phantom.
        """Conjoin conditions while retaining both static and runtime source sets."""

        return cast(
            "Predicate[Scope_co | OtherScope]",
            Predicate(
                f"({self.sql}) AND ({other.sql})",
                self.owners | other.owners,
                self.parameters + other.parameters,
            ),
        )


@dataclass(frozen=True)
class Selection(Generic[Scope_co, Value]):
    """One typed result slot, potentially decoded from several SQL columns."""

    sql: tuple[str, ...]
    owners: frozenset[Token]
    decode: Callable[[tuple[object, ...]], Value]


@dataclass(frozen=True)
class Expression(Generic[Scope_co, Value]):
    """A scoped scalar SQL expression with logical-value encoding and decoding."""

    sql: str
    owners: frozenset[Token]
    decode: Callable[[object], Value]
    encode: Callable[[Value], object]

    def eq(self, value: Value) -> Predicate[Scope_co]:
        """Compare with a bound logical value; None produces IS NULL rather than =."""

        if value is None:
            return Predicate(f"{self.sql} IS NULL", self.owners)
        return Predicate(f"{self.sql} = ?", self.owners, (self.encode(value),))

    def eq_col[OtherScope](
        self, other: Expression[OtherScope, Value]
    ) -> Predicate[Scope_co | OtherScope]:
        """Compare same-domain expressions while retaining both source scopes."""

        return Predicate[Scope_co | OtherScope](
            f"{self.sql} = {other.sql}", self.owners | other.owners
        )

    def eq_nullable[OtherScope](
        self, other: Expression[OtherScope, Value | None]
    ) -> Predicate[Scope_co | OtherScope]:
        """Compare against an optional expression and retain both source scopes.

        This emits ordinary SQL equality, not NULL-safe equality. It is useful
        for joining a nonnullable key to a nullable FK or outer-source column."""

        return Predicate[Scope_co | OtherScope](
            f"{self.sql} = {other.sql}", self.owners | other.owners
        )

    def like(
        self: Expression[Scope_co, str] | Expression[Scope_co, str | None], pattern: str
    ) -> Predicate[Scope_co]:
        """Match a string pattern; nullable strings retain ordinary SQL NULL behavior."""

        return Predicate(f"{self.sql} LIKE ?", self.owners, (pattern,))


@dataclass(frozen=True)
class Source(Generic[InvariantScope, Owner]):
    """A read table occurrence whose columns and whole rows share one query scope."""

    row_type: type[Owner]
    role: type[object] | str | None = None
    name: str | None = None

    @property
    def token(self) -> Token:
        """Identify this occurrence at runtime by table, role, nullability, and SQL name."""

        return (
            self.row_type,
            self.role,
            False,
            (self.name or self.row_type.table_name).casefold(),
        )

    @property
    def sql(self) -> str:
        """Render the quoted table and optional alias for a FROM or JOIN clause."""

        table = _quote(self.row_type.table_name)
        return table if self.name is None else f"{table} AS {_quote(self.name)}"

    def column[Value](
        self, column: Column[Owner, Value]
    ) -> Expression[InvariantScope, Value]:
        """Bind a model column to this occurrence without changing its value type.

        The expression qualifies SQL with this source name and uses the column's
        adapter for logical-value validation, encoding, and decoding."""

        if column.owner is not self.row_type:
            message = "Column belongs to another source"
            raise ModelError(message)
        adapter = self.row_type.specs[column.name].adapter

        def decode(raw: object) -> Value:
            # The descriptor's value coordinate names exactly this adapter's logical type.
            return cast("Value", adapter.validate_python(raw))

        def encode(value: Value) -> object:
            return adapter.dump_python(
                adapter.validate_python(value, strict=True), mode="json"
            )

        return Expression(
            f"{_quote(self.name or self.row_type.table_name)}.{_quote(column.name)}",
            frozenset({self.token}),
            decode,
            encode,
        )

    def row(self) -> Selection[InvariantScope, Owner]:
        """Select all model fields as one result slot containing a read-model instance."""

        names = tuple(self.row_type.specs)

        def decode(raw: tuple[object, ...]) -> Owner:
            values = {
                name: self.row_type.specs[name].adapter.validate_python(value)
                for name, value in zip(names, raw, strict=True)
            }
            return self.row_type(**values)

        return Selection(
            tuple(
                f"{_quote(self.name or self.row_type.table_name)}.{_quote(name)}"
                for name in names
            ),
            frozenset({self.token}),
            decode,
        )


@dataclass(frozen=True)
class OuterSource(Generic[InvariantScope, Owner]):
    """A LEFT JOIN occurrence with optional scalar and whole-row selections."""

    row_type: type[Owner]
    role: type[object]
    name: str

    @property
    def token(self) -> Token:
        """Identify the nullable occurrence separately from its nonnullable alias."""

        return self.row_type, self.role, True, self.name.casefold()

    @property
    def sql(self) -> str:
        """Render the quoted table and alias for the nullable join source."""

        return f"{_quote(self.row_type.table_name)} AS {_quote(self.name)}"

    def column[Value](
        self, column: Column[Owner, Value]
    ) -> Expression[Outer[InvariantScope], Value | None]:
        """Bind a column with Outer scope and lift its logical value type to T | None."""

        original = Source[InvariantScope, Owner](
            self.row_type, self.role, self.name
        ).column(column)
        return Expression[Outer[InvariantScope], Value | None](
            original.sql,
            frozenset({self.token}),
            lambda raw: None if raw is None else original.decode(raw),
            lambda value: None if value is None else original.encode(value),
        )

    def row[Value](
        self, *, present: Column[Owner, Value]
    ) -> Selection[Outer[InvariantScope], Owner | None]:
        """Select a read row or None using a nonnullable presence column.

        A SQL NULL in the witness means no right-hand row matched. The prototype
        checks the tested annotation forms only; full alias/nullability inspection
        is not implemented. Other nullable fields are not absence witnesses."""

        logical_type = self.row_type.specs[present.name].logical_type
        if present.owner is not self.row_type or type(None) in get_args(logical_type):
            message = "Presence witness must be a nonnullable column of this source"
            raise ModelError(message)
        original = Source[InvariantScope, Owner](
            self.row_type, self.role, self.name
        ).row()
        return Selection[Outer[InvariantScope], Owner | None](
            (f"{_quote(self.name)}.{_quote(present.name)}", *original.sql),
            frozenset({self.token}),
            lambda raw: None if raw[0] is None else original.decode(raw[1:]),
        )


@dataclass(frozen=True)
class Mapped(Generic[Value]):
    """Terminal Python materialization, not an embeddable SQL expression."""

    execute: Callable[[Connection], Awaitable[list[Value]]]

    async def fetch(self, connection: Connection) -> list[Value]:
        """Fetch the underlying query and apply its Python result factory to each row."""

        return await self.execute(connection)


@dataclass(frozen=True)
class Query(Generic[InvariantScope, ReadyState, *Values]):
    """An immutable SELECT carrying available sources, readiness, and result slots."""

    base: Source[Any, Any]
    selections: tuple[Selection[Any, Any], ...] = ()
    conditions: tuple[Predicate[Any], ...] = ()
    scoped: bool = False
    joins: tuple[
        tuple[str, Source[Any, Any] | OuterSource[Any, Any], Predicate[Any]], ...
    ] = ()

    def add[Value](
        self,
        selection: Selection[InvariantScope, Value] | Expression[InvariantScope, Value],
    ) -> Query[InvariantScope, ReadyState, *Values, Value]:
        """Append one result slot from an available source, preserving the flat tuple type."""

        if isinstance(selection, Expression):
            expression = selection
            selection = Selection(
                (expression.sql,),
                expression.owners,
                lambda raw: expression.decode(raw[0]),
            )
        return Query(
            self.base,
            (*self.selections, selection),
            self.conditions,
            self.scoped,
            self.joins,
        )

    def where(
        self, condition: Predicate[InvariantScope]
    ) -> Query[InvariantScope, Ready, *Values]:
        """Append an AND condition and mark the query as explicitly scoped."""

        return Query(
            self.base, self.selections, (*self.conditions, condition), True, self.joins
        )

    def all(self) -> Query[InvariantScope, Ready, *Values]:
        """Allow execution without a WHERE clause; existing conditions are retained."""

        return Query(self.base, self.selections, self.conditions, True, self.joins)

    def join[OtherScope, Other: ReadRow](
        self: Query[InvariantScope, ReadyState, *Values],
        other: Source[OtherScope, Other],
        *,
        on: Predicate[InvariantScope | OtherScope],
    ) -> Query[InvariantScope | OtherScope, ReadyState, *Values]:
        # SQL source membership is stored in joins; ty loses the phantom union
        # coordinate while constructing this legacy variadic generic.
        """Add an inner-join source and extend the available scope for later expressions."""

        return cast(
            "Query[InvariantScope | OtherScope, ReadyState, *Values]",
            Query(
                self.base,
                self.selections,
                self.conditions,
                self.scoped,
                (*self.joins, ("JOIN", other, on)),
            ),
        )

    def left_join[OtherScope, Other: ReadRow](
        self: Query[InvariantScope, ReadyState, *Values],
        other: OuterSource[OtherScope, Other],
        *,
        on: Predicate[InvariantScope | Outer[OtherScope]],
    ) -> Query[InvariantScope | Outer[OtherScope], ReadyState, *Values]:
        # The new scope uses Outer, so nonnullable views cannot satisfy it.
        """Add a nullable right-hand source and extend scope with its Outer identity."""

        return cast(
            "Query[InvariantScope | Outer[OtherScope], ReadyState, *Values]",
            Query(
                self.base,
                self.selections,
                self.conditions,
                self.scoped,
                (*self.joins, ("LEFT JOIN", other, on)),
            ),
        )

    def map[First, *Rest, Result](
        self: Query[InvariantScope, Ready, First, *Rest],
        factory: Callable[[*Values], Result],
    ) -> Mapped[Result]:
        """Finish an executable, nonempty projection with a checked Python factory.

        Positional projection types must satisfy the factory's arguments. This is
        terminal materialization, not a SQL expression or an embeddable subquery."""

        async def execute(connection: Connection) -> list[Result]:
            return [factory(*row) for row in await self._fetch(connection)]

        return Mapped(execute)

    async def fetch[First, *Rest](
        self: Query[InvariantScope, Ready, First, *Rest], connection: Connection
    ) -> list[tuple[First, *Rest]]:
        """Execute a scoped, nonempty projection and return its decoded result tuples."""

        return await self._fetch(connection)

    async def _fetch(self, connection: Connection) -> list[tuple[*Values]]:
        """Validate runtime source membership, then compile and decode the SELECT.

        Runtime checks still matter after static checking: alias names can differ
        despite sharing a role type, and dynamic callers can bypass readiness."""

        if not self.scoped or not self.selections:
            message = "Query needs row scope and a projection"
            raise ModelError(message)
        owners = frozenset({self.base.token})
        visible_names = {(self.base.name or self.base.row_type.table_name).casefold()}
        roles = {self.base.token[:3]}
        join_parameters: tuple[object, ...] = ()
        join_sql: list[str] = []
        for kind, table, condition in self.joins:
            name = (table.name or table.row_type.table_name).casefold()
            if name in visible_names or table.token[:3] in roles:
                message = "Duplicate source identity or SQL name"
                raise ModelError(message)
            owners = owners | {table.token}
            if not condition.owners <= owners:
                message = "ON refers to an unavailable source"
                raise ModelError(message)
            visible_names.add(name)
            roles.add(table.token[:3])
            join_sql.append(f"{kind} {table.sql} ON {condition.sql}")
            join_parameters += condition.parameters
        used = frozenset(
            owner
            for item in (*self.selections, *self.conditions)
            for owner in item.owners
        )
        if not used <= owners:
            message = "Expression refers to a source outside this query"
            raise ModelError(message)
        fields = ", ".join(
            sql for selection in self.selections for sql in selection.sql
        )
        sql = f"SELECT {fields} FROM {self.base.sql} " + " ".join(join_sql)
        if self.conditions:
            sql += " WHERE " + " AND ".join(f"({item.sql})" for item in self.conditions)
        parameters = join_parameters + tuple(
            value for condition in self.conditions for value in condition.parameters
        )
        async with connection.execute(sql, parameters) as cursor:
            rows = await cursor.fetchall()
        decoded: list[tuple[*Values]] = []
        for raw in rows:
            offset = 0
            values: list[object] = []
            for selection in self.selections:
                width = len(selection.sql)
                values.append(selection.decode(tuple(raw[offset : offset + width])))
                offset += width
            # Each add appends the decoder and its type coordinate together.
            decoded.append(cast("tuple[*Values]", tuple(values)))
        return decoded


def source[Owner: ReadRow](row: type[Owner]) -> Source[Owner, Owner]:
    """Bind a read model as an unaliased FROM source.

    `.column(Model.field)` creates scoped expressions; `.row()` selects a whole
    read object. The row class also supplies the static source identity, so use
    `alias` for multiple occurrences of the same table. New/input classes do not
    satisfy this function's ReadRow type bound. No query is executed here.

    ```python
    from scratchpad.dual_features.models import Account

    accounts = source(Account)
    names = select(accounts).add(accounts.column(Account.name)).all()
    ```"""

    return Source(row)


def select[Scope_co, Owner: ReadRow](
    table: Source[Scope_co, Owner],
) -> Query[Scope_co, Unscoped]:
    """Start a SELECT with no projection and no explicit row scope.

    Add result slots with `.add(...)` and supply `.where(...)` or `.all()` before
    fetching or mapping results. Each slot appends one type to the result tuple,
    including a whole model selected with `.row()`. Join a source before adding
    expressions that refer to it. This function only builds query state.

    ```python
    from scratchpad.dual_features.models import Account

    accounts = source(Account)
    query = select(accounts).add(accounts.row()).all()
    ```"""

    return Query(table)


def alias[Owner: ReadRow, Role](
    row: type[Owner], role: type[Role], *, name: str
) -> Source[Alias[Owner, Role], Owner]:
    """Give a read table a nominal role type and a SQL alias name.

    The role class distinguishes scopes statically; name qualifies emitted SQL.
    Use distinct role classes and names for separate occurrences of a table.
    Returning rows still have the original model type. Runtime identity checks
    also compare names, since a role type alone cannot prove alias identity.

    ```python
    from scratchpad.dual_features.models import Account

    class Manager:
        pass

    managers = alias(Account, Manager, name="manager")
    manager_name = managers.column(Account.name)
    ```"""

    return Source(row, role, name)


def outer[Owner: ReadRow, Role](
    row: type[Owner], role: type[Role], *, name: str
) -> OuterSource[Alias[Owner, Role], Owner]:
    """Create the nullable right-hand source for `.left_join(...)`.

    Role identifies the alias statically; name identifies it in SQL. Columns
    expose `T | None` under a distinct Outer scope, so a nonnullable alias cannot
    substitute for this view. `.row(present=...)` exposes `Row | None` using a
    nonnullable presence column. Creating this view does not itself add a join.

    ```python
    from scratchpad.dual_features.models import Account, Entry

    class EntryRole:
        pass

    accounts = source(Account)
    entries = outer(Entry, EntryRole, name="entry")
    query = select(accounts).left_join(
        entries,
        on=accounts.column(Account.id).eq_nullable(entries.column(Entry.account_id)),
    ).add(entries.column(Entry.note)).all()
    ```"""

    return OuterSource(row, role, name)


Outcome = TypeVar("Outcome")
AssignmentState = TypeVar("AssignmentState")


class Assigned:
    """At least one assignment exists."""


class Unassigned:
    """Missing update assignments."""


@dataclass(frozen=True)
class Attempted(Generic[Owner]):
    """A conflict-only assignment using the value proposed by the current insert."""

    column: str
    owner: type[Owner]


@dataclass(frozen=True)
class InsertPlan(Generic[Owner, Outcome]):
    """A prepared SQLite insert whose outcome changes with conflict handling."""

    row_type: type[Owner]
    values: Mapping[str, object]
    target: str | None = None
    replacements: tuple[Assignment[Owner] | Attempted[Owner], ...] = ()
    ignore: bool = False

    def on_conflict[Value](
        self,
        target: Column[Owner, Value],
        first: Assignment[Owner] | Attempted[Owner],
        *rest: Assignment[Owner] | Attempted[Owner],
    ) -> InsertPlan[Owner, Owner]:
        """Update the conflicting row using literal or attempted-value assignments.

        The target and assignments must belong to this table. SQLite must also
        recognize the target as a suitable unique key. The result remains a row."""

        if target.owner is not self.row_type or any(
            item.owner is not self.row_type for item in (first, *rest)
        ):
            message = "Conflict clauses belong to another table"
            raise ModelError(message)
        return InsertPlan(self.row_type, self.values, target.name, (first, *rest))

    def ignore_conflict[Value](
        self, target: Column[Owner, Value]
    ) -> InsertPlan[Owner, Owner | None]:
        """Skip a target-key conflict and change the result type to Row | None."""

        if target.owner is not self.row_type:
            message = "Conflict target belongs to another table"
            raise ModelError(message)
        return InsertPlan(self.row_type, self.values, target.name, ignore=True)

    async def execute(self, connection: Connection) -> Outcome:
        """Execute INSERT RETURNING without committing; skipped conflicts return None."""

        sql, parameters = self._compile(returning=True)
        async with connection.execute(sql, parameters) as cursor:
            raw = await cursor.fetchone()
        if raw is None:
            if not self.ignore:
                message = "A returning write unexpectedly produced no row"
                raise ModelError(message)
            # Only ignore_conflict promises an optional outcome.
            return cast("Outcome", None)
        values = {
            name: spec.adapter.validate_python(value)
            for (name, spec), value in zip(
                self.row_type.specs.items(), raw, strict=True
            )
        }
        return cast("Outcome", self.row_type(**values))

    def _compile(self, *, returning: bool) -> tuple[str, tuple[object, ...]]:
        """Compile the same validated write with or without a RETURNING clause."""
        names = tuple(self.values)
        parameters: list[object] = [
            self.row_type.specs[name].adapter.dump_python(
                self.values[name], mode="json"
            )
            for name in names
        ]
        sql = (
            f"INSERT INTO {_quote(self.row_type.table_name)} ({', '.join(_quote(name) for name in names)}) VALUES ({', '.join('?' for _ in names)})"
            if names
            else f"INSERT INTO {_quote(self.row_type.table_name)} DEFAULT VALUES"
        )
        if self.target is not None:
            sql += f" ON CONFLICT ({_quote(self.target)}) DO "
            if self.ignore:
                sql += "NOTHING"
            else:
                assignments: list[str] = []
                for item in self.replacements:
                    if isinstance(item, Attempted):
                        assignments.append(
                            f"{_quote(item.column)} = excluded.{_quote(item.column)}"
                        )
                    else:
                        adapter = self.row_type.specs[item.name].adapter
                        parameters.append(
                            adapter.dump_python(
                                adapter.validate_python(item.value, strict=True),
                                mode="json",
                            )
                        )
                        assignments.append(f"{_quote(item.name)} = ?")
                sql += "UPDATE SET " + ", ".join(assignments)
        if returning:
            sql += " RETURNING " + ", ".join(
                _quote(name) for name in self.row_type.specs
            )
        return sql, tuple(parameters)


@dataclass(frozen=True)
class Update(Generic[Owner, AssignmentState, ReadyState]):
    """An immutable UPDATE tracking assignments and explicit row scope separately."""

    row_type: type[Owner]
    assignments: tuple[Assignment[Owner], ...] = ()
    conditions: tuple[Predicate[Owner], ...] = ()
    scoped: bool = False

    def set(
        self, first: Assignment[Owner], *rest: Assignment[Owner]
    ) -> Update[Owner, Assigned, ReadyState]:
        """Append assignments from this table and mark the update as assigned."""

        if any(item.owner is not self.row_type for item in (first, *rest)):
            message = "Assignment belongs to another table"
            raise ModelError(message)
        return Update(
            self.row_type,
            (*self.assignments, first, *rest),
            self.conditions,
            self.scoped,
        )

    def where(
        self, condition: Predicate[Owner]
    ) -> Update[Owner, AssignmentState, Ready]:
        """Append an AND condition and mark the update as explicitly scoped."""

        return Update(
            self.row_type, self.assignments, (*self.conditions, condition), True
        )

    def all(self) -> Update[Owner, AssignmentState, Ready]:
        """Allow a whole-table update; this does not remove existing WHERE conditions."""

        return Update(self.row_type, self.assignments, self.conditions, True)

    async def execute(
        self: Update[Owner, Assigned, Ready], connection: Connection
    ) -> list[Owner]:
        """Execute a scoped, assigned UPDATE RETURNING without committing the transaction."""

        sql, parameters = self._compile(returning=True)
        async with connection.execute(sql, parameters) as cursor:
            rows = await cursor.fetchall()
        return [
            self.row_type(
                **{
                    name: spec.adapter.validate_python(value)
                    for (name, spec), value in zip(
                        self.row_type.specs.items(), raw, strict=True
                    )
                }
            )
            for raw in rows
        ]

    def _compile(
        self: Update[Owner, Assigned, Ready], *, returning: bool
    ) -> tuple[str, tuple[object, ...]]:
        """Compile the same validated write with or without a RETURNING clause."""
        if not self.scoped or not self.assignments:
            message = "Update needs assignments and row scope"
            raise ModelError(message)
        if any(
            condition.owners - {source(self.row_type).token}
            for condition in self.conditions
        ):
            message = "Update condition refers to another source"
            raise ModelError(message)
        parameters: list[object] = []
        clauses: list[str] = []
        for assignment in self.assignments:
            adapter = self.row_type.specs[assignment.name].adapter
            parameters.append(
                adapter.dump_python(
                    adapter.validate_python(assignment.value, strict=True), mode="json"
                )
            )
            clauses.append(f"{_quote(assignment.name)} = ?")
        sql = f"UPDATE {_quote(self.row_type.table_name)} SET {', '.join(clauses)}"
        if self.conditions:
            sql += " WHERE " + " AND ".join(
                f"({condition.sql})" for condition in self.conditions
            )
            parameters.extend(
                value for condition in self.conditions for value in condition.parameters
            )
        if returning:
            sql += " RETURNING " + ", ".join(
                _quote(name) for name in self.row_type.specs
            )
        return sql, tuple(parameters)


def attempted[Owner: ReadRow, Value](column: Column[Owner, Value]) -> Attempted[Owner]:
    """Use the proposed insert value for a column during a conflict update.

    This represents SQLite's excluded-column value. It is accepted by
    `.on_conflict(...)`, not ordinary `update(...).set(...)`; it neither reads
    a Python row attribute nor generates a fresh default during the update.

    ```python
    from scratchpad.dual_features.models import Account

    plan = insert(Account.create(name="Ada", code="A")).on_conflict(
        Account.code, attempted(Account.name)
    )
    ```"""

    return Attempted(column.name, column.owner)


def insert[Owner: ReadRow](command: Insert[Owner]) -> InsertPlan[Owner, Owner]:
    """Turn a constructor command into an executable SQLite insert plan.

    `.execute(connection)` inserts the prepared values and materializes the read
    model through RETURNING. Omitted generated fields are absent from the command;
    explicit None values remain SQL NULL. Input/read row instances are not the
    command interface. The caller owns the connection and transaction boundary.

    ```python
    from scratchpad.dual_features.models import Account

    plan = insert(Account.create(name="Ada", code="A"))
    ```"""

    return InsertPlan(command.row_type, command.values)


def update[Owner: ReadRow](row: type[Owner]) -> Update[Owner, Unassigned, Unscoped]:
    """Start an UPDATE without assignments or an explicit row scope.

    Execution requires `.set(...)` and either `.where(...)` or `.all()`, in either
    order. Assignments and predicates must belong to this read table. Execution
    returns a list of materialized read rows and does not commit the transaction.
    Generated columns remain assignable; database constraints still apply.

    ```python
    from scratchpad.dual_features.models import Account

    accounts = source(Account)
    plan = update(Account).where(accounts.column(Account.id).eq(1)).set(
        Account.name.to("Augusta")
    )
    ```"""

    return Update(row)


@dataclass(frozen=True)
class CompositeReference(Generic[Owner, Target]):
    """Ordered scalar pairs forming a single composite join and FK constraint."""

    pairs: tuple[Reference[Owner, Target, Any], ...]

    def on[LeftScope, RightScope](
        self, source: Source[LeftScope, Owner], target: Source[RightScope, Target]
    ) -> Predicate[LeftScope | RightScope]:
        """Bind every pair to the same two sources and combine comparisons with AND."""

        if not self.pairs:
            message = "Composite reference has no pairs"
            raise ModelError(message)
        condition = self.pairs[0].on(source, target)
        for pair in self.pairs[1:]:
            condition = condition & pair.on(source, target)
        return condition

    def and_[Value](
        self, other: Reference[Owner, Target, Value]
    ) -> CompositeReference[Owner, Target]:
        """Append a pair after checking table identity, column reuse, and enforcement."""

        if not self.pairs:
            message = "Composite reference needs at least one pair"
            raise ModelError(message)
        first = self.pairs[0]
        if (
            other.source.owner is not first.source.owner
            or other.target.owner is not first.target.owner
        ):
            message = "Composite reference mixes tables"
            raise ModelError(message)
        if any(
            pair.source.name == other.source.name
            or pair.target.name == other.target.name
            for pair in self.pairs
        ):
            message = "Composite reference repeats columns"
            raise ModelError(message)
        if any(pair.enforced != other.enforced for pair in self.pairs):
            message = "Composite reference mixes enforced and soft members"
            raise ModelError(message)
        return CompositeReference((*self.pairs, other))

    def ddl(self) -> str:
        """Emit one ordered composite FK fragment, or no DDL for soft references."""

        if not self.pairs or not self.pairs[0].enforced:
            return ""
        source_columns = ", ".join(_quote(pair.source.name) for pair in self.pairs)
        target_columns = ", ".join(_quote(pair.target.name) for pair in self.pairs)
        return f"FOREIGN KEY ({source_columns}) REFERENCES {_quote(self.pairs[0].target.owner.table_name)} ({target_columns})"


class Relationship[From: ReadRow, To: ReadRow](Protocol):
    """Only table roles remain after field-domain compatibility is checked."""

    def on[LeftScope, RightScope](
        self, source: Source[LeftScope, From], target: Source[RightScope, To]
    ) -> Predicate[LeftScope | RightScope]:
        """Bind the relationship to table occurrences and retain both query scopes."""
        ...

    def ddl(self) -> str:
        """Emit an FK constraint fragment, or no DDL when enforcement is disabled."""
        ...


@overload
def relationship[From: ReadRow, To: ReadRow, Value](
    source: Column[From, Value | None],
    target: Column[To, Value | None],
    *,
    enforced: bool = True,
) -> Relationship[From, To]: ...
@overload
def relationship[From: ReadRow, To: ReadRow, Value](
    source: Column[From, Value | None],
    target: Column[To, Value],
    *,
    enforced: bool = True,
) -> Relationship[From, To]: ...
@overload
def relationship[From: ReadRow, To: ReadRow, Value](
    source: Column[From, Value],
    target: Column[To, Value | None],
    *,
    enforced: bool = True,
) -> Relationship[From, To]: ...
@overload
def relationship[From: ReadRow, To: ReadRow, Value](
    source: Column[From, Value], target: Column[To, Value], *, enforced: bool = True
) -> Relationship[From, To]: ...
def relationship[From: ReadRow, To: ReadRow](
    source: Column[From, Any], target: Column[To, Any], *, enforced: bool = True
) -> Relationship[From, To]:
    # Value erasure stays inside the implementation. The overloads check the
    # domains; the returned protocol exposes table roles, not Any-valued columns.
    """Declare a typed scalar relationship between two read-model columns.

    Overloads check logical value compatibility for all four combinations of
    nullable/nonnullable source and target. The result keeps the two table types
    while hiding the checked value coordinate. `.on(source, target)` builds a
    join predicate using concrete source or alias objects.

    `enforced=False` retains the join metadata but makes `.ddl()` empty. Otherwise
    `.ddl()` emits an FK fragment; this call does not install it or validate
    candidate keys, storage compatibility, backend identity, or FK actions.

    ```python
    from scratchpad.dual_features.models import Account, Entry

    edge = relationship(Entry.account_id, Account.id)
    condition = edge.on(source(Entry), source(Account))
    ```"""

    return ReferenceFrom[From, Any](source).to(target, enforced=enforced)


def composite[From: ReadRow, To: ReadRow](
    first: Relationship[From, To],
    second: Relationship[From, To],
    *rest: Relationship[From, To],
) -> Relationship[From, To]:
    """Group at least two scalar relationships into one composite reference.

    Members must come from `relationship` and share source table, target table,
    and enforcement policy. Repeated source or target columns are rejected.
    Nested composites are not accepted. Declaration order fixes column pairing;
    types cannot prove the business meaning of same-typed members.

    `.on(...)` combines comparisons with AND. `.ddl()` emits one composite FK,
    not independent constraints; the schema still needs a suitable target key.
    SQLite skips FK enforcement when any source member is NULL.

    ```python
    from scratchpad.dual_features.models import Account, Entry

    edge = composite(
        relationship(Entry.account_id, Account.id),
        relationship(Entry.note, Account.code),
    )
    ```"""

    edges = (first, second, *rest)
    if not all(isinstance(edge, Reference) for edge in edges):
        message = "Composite members must come from the relationship factory"
        raise ModelError(message)
    # Factory-produced references implement the invariant From/To protocol.
    # Only the already-checked heterogeneous value coordinate is erased here.
    pairs = cast("tuple[Reference[From, To, Any], ...]", edges)
    grouped = CompositeReference[From, To]((pairs[0],))
    for pair in pairs[1:]:
        grouped = grouped.and_(pair)
    return grouped


def named_alias[Owner: ReadRow, Name: LiteralString](
    row: type[Owner], *, name: Name
) -> Source[Alias[Owner, Name], Owner]:
    """Use a literal SQL name as the alias's static identity.

    Under the tested ty version, a direct literal preserves its exact Literal
    type, so different names distinguish scopes without role classes. Passing a
    broadly annotated LiteralString loses that precision. Prefer `alias` with a
    nominal role for generated names or helpers that cannot preserve literals.

    ```python
    from scratchpad.dual_features.models import Account

    managers = named_alias(Account, name="manager")
    reviewers = named_alias(Account, name="reviewer")
    ```"""

    return Source(row, name, name)
