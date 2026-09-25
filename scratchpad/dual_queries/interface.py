"""Throwaway query interfaces over the earlier bounded SQLite implementation.

Direct model/column selections avoid explicit sources. Source scope, projection
requirements, and readiness remain private coordinates, not application types.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import (
    Any,
    Generic,
    LiteralString,
    Protocol,
    TypeVar,
    TypeVarTuple,
    cast,
    overload,
)

from aiosqlite import Connection

from scratchpad.dual_features.models import ReadRow
from scratchpad.dual_features.records import Column, ForeignColumn, ModelError
from scratchpad.dual_features.runtime import (
    Alias,
    Expression,
    Outer,
    OuterSource,
    Predicate,
    Ready,
    Selection,
    Source,
    Unscoped,
)
from scratchpad.dual_features.runtime import (
    Query as CoreQuery,
)
from scratchpad.dual_features.runtime import (
    Relationship as LegacyRelationship,
)
from scratchpad.dual_features.runtime import (
    composite as legacy_composite,
)
from scratchpad.dual_features.runtime import (
    relationship as legacy_relationship,
)
from scratchpad.dual_features.runtime import (
    source as legacy_source,
)
from scratchpad.dual_queries.relationships import (
    Referenced,
    ReferenceTarget,
    reference_predicate,
)

Scope = TypeVar("Scope")
Target = TypeVar("Target", bound=ReadRow)
Needed_co = TypeVar("Needed_co", covariant=True)
State = TypeVar("State")
Result = TypeVar("Result")
ComparisonValue_co = TypeVar("ComparisonValue_co", covariant=True)
Row = TypeVar("Row", bound=ReadRow)
Values = TypeVarTuple("Values")
From = TypeVar("From", bound=ReadRow)
To = TypeVar("To", bound=ReadRow)


@dataclass(frozen=True)
class Occurrence(Generic[Scope, Row]):
    """Invariant source witness prevents join arguments from widening ownership."""

    raw: Source[Scope, Row] | OuterSource[Any, Row]


class Table[Scope, Row: ReadRow](Protocol):
    """A read class or alias supplies an invariant source witness."""

    def __source__(self) -> Occurrence[Scope, Row]: ...


@dataclass(frozen=True)
class Item(Generic[Scope, Result]):
    """One projected value with an invariant source identity and exact decoder."""

    source: Source[Any, Any] | OuterSource[Any, Any]
    selection: Selection[Scope, Result]

    def __selection__(self) -> Item[Scope, Result]:
        return self


class Selectable[Scope, Result](Protocol):
    """Models, columns, and alias expressions retain their source and result."""

    def __selection__(self) -> Item[Scope, Result]: ...


@dataclass(frozen=True)
class Comparison(Generic[Scope, ComparisonValue_co]):
    """Read-only value witness; scope stays invariant while NULL can be lifted.

    The SQL expression's value coordinate is erased only inside this witness.
    The typed decoder preserves its logical result without exposing value writes.
    """

    expression: Expression[Scope, Any]
    decode: Callable[[object], ComparisonValue_co]


class Comparable[Scope, Value](Protocol):
    """A scalar can supply its SQL identity and covariant read-value witness."""

    def __comparison__(self) -> Comparison[Scope, Value]: ...


@dataclass(frozen=True)
class Projection(Generic[Scope, Needed_co, Result]):
    """Reusable SELECT fields plus materialization, not an SQL scalar expression."""

    source: Source[Any, Any] | OuterSource[Any, Any]
    selections: tuple[Selection[Any, Any], ...]
    decode: Callable[[tuple[object, ...]], Result]


class Columns(
    Projection[Scope, Needed_co, tuple[*Values]], Generic[Scope, Needed_co, *Values]
):
    """Unbounded flat result slots; `columns(Account.name).add(Account.id)`."""

    def add[OtherScope, Value](
        self, item: Selectable[OtherScope, Value]
    ) -> Columns[Scope, Needed_co | OtherScope, *Values, Value]:
        """Append a slot without requiring its source to be joined yet."""
        slot = item.__selection__()
        # All elements have already been decoded by the corresponding selections.
        # Constructor inference loses phantom unions and packs; no caller cast is needed.
        return cast(
            "Columns[Scope, Needed_co | OtherScope, *Values, Value]",
            Columns(self.source, (*self.selections, slot.selection), lambda row: row),
        )

    def into[MappedResult](
        self, factory: Callable[[*Values], MappedResult]
    ) -> Projection[Scope, Needed_co, MappedResult]:
        """Bind a checked positional constructor or keyword-building lambda.

        `columns(Account.name, Account.id).into(Summary)` checks both arguments.
        The factory runs after SQLite returns decoded values. The result remains
        a projection, never a SQL value that supports comparisons or arithmetic.
        """
        return Projection[Scope, Needed_co, MappedResult](
            self.source, self.selections, lambda row: factory(*self.decode(row))
        )


@dataclass(frozen=True)
class Scalar(Generic[Scope, Result]):
    """A read-only alias expression, not a writable model column."""

    source: Source[Any, Any] | OuterSource[Any, Any]
    expression: Expression[Scope, Result]

    def __selection__(self) -> Item[Scope, Result]:
        return Item(
            self.source,
            Selection(
                (self.expression.sql,),
                self.expression.owners,
                lambda raw: self.expression.decode(raw[0]),
            ),
        )

    def __scalar__(self) -> Expression[Scope, Result]:
        return self.expression

    def eq(self, value: Result) -> Predicate[Scope]:
        """Compare a logical value, using IS NULL for None."""
        return self.expression.eq(value)

    def __comparison__(self) -> Comparison[Scope, Result]:
        return Comparison(self.expression, self.expression.decode)

    def eq_col[Other](
        self, other: Comparable[Other, Result | None]
    ) -> Predicate[Scope | Other]:
        """Compare compatible read values without losing either operand's scope."""
        right = other.__comparison__().expression
        return Predicate[Scope | Other](
            f"{self.expression.sql} = {right.sql}",
            self.expression.owners | right.owners,
        )

    def like(
        self: Scalar[Scope, str] | Scalar[Scope, str | None], pattern: str
    ) -> Predicate[Scope]:
        """Match optional text using ordinary SQL NULL semantics."""
        return self.expression.like(pattern)


@dataclass(frozen=True)
class BoundScalar(Scalar[Scope, Result], Generic[Scope, Row, Result]):
    """Alias scalar preserving the original model and column as a reference target."""

    original: Column[Row, Any]

    def __reference__(self) -> ReferenceTarget[Scope, Row, Result]:
        return ReferenceTarget(self.original, self.expression, self.expression.decode)


@dataclass(frozen=True)
class ForeignScalar(
    BoundScalar[Scope, Row, Result], Generic[Scope, Row, Target, Result]
):
    """An alias of a declared FK keeps target identity as well as nullable scope."""

    foreign: ForeignColumn[Row, Target, Any]

    def references[Other](
        self, target: Referenced[Other, Target, Result | None]
    ) -> Predicate[Scope | Other]:
        """Bind named columns explicitly, including self joins and optional roles."""
        return reference_predicate(
            self.foreign, self.expression, target.__reference__()
        )


@dataclass(frozen=True)
class TableAlias(Generic[Scope, Row]):
    """A nominal SQL role with exact original-column binding."""

    source: Source[Scope, Row]

    def __source__(self) -> Occurrence[Scope, Row]:
        return Occurrence(self.source)

    def __selection__(self) -> Item[Scope, Row]:
        return Item(self.source, self.source.row())

    @overload
    def column[Target: ReadRow, Value](
        self, column: ForeignColumn[Row, Target, Value]
    ) -> ForeignScalar[Scope, Row, Target, Value]: ...
    @overload
    def column[Value](
        self, column: Column[Row, Value]
    ) -> BoundScalar[Scope, Row, Value]: ...
    def column(self, column: Column[Row, Any]) -> BoundScalar[Scope, Row, Any]:
        """Bind original columns without losing an FK's declared target."""
        expression = self.source.column(column)
        if isinstance(column, ForeignColumn):
            return ForeignScalar(self.source, expression, column, column)
        return BoundScalar(self.source, expression, column)


@dataclass(frozen=True)
class NullableAlias(Generic[Scope, Row]):
    """A left-join-only role; it cannot masquerade as an ordinary inner source."""

    source: OuterSource[Scope, Row]

    def __outer_source__(self) -> Occurrence[Outer[Scope], Row]:
        return Occurrence(self.source)

    @overload
    def column[Target: ReadRow, Value](
        self, column: ForeignColumn[Row, Target, Value]
    ) -> ForeignScalar[Outer[Scope], Row, Target, Value | None]: ...
    @overload
    def column[Value](
        self, column: Column[Row, Value]
    ) -> BoundScalar[Outer[Scope], Row, Value | None]: ...
    def column(self, column: Column[Row, Any]) -> BoundScalar[Outer[Scope], Row, Any]:
        """Lift nullability while preserving the original FK declaration."""
        expression = self.source.column(column)
        if isinstance(column, ForeignColumn):
            return ForeignScalar(self.source, expression, column, column)
        return BoundScalar(self.source, expression, column)

    def row[Value](
        self, *, present: Column[Row, Value]
    ) -> Item[Outer[Scope], Row | None]:
        """Select the optional row using a runtime-checked nonnullable witness."""
        return Item(self.source, self.source.row(present=present))


def outer[Row: ReadRow, Role](
    row: type[Row], role: type[Role], *, name: str
) -> NullableAlias[Alias[Row, Role], Row]:
    """Declare an optional right-hand role; add it with `.left_join(...)`."""
    return NullableAlias(OuterSource(row, role, name))


def alias[Row: ReadRow, Role](
    row: type[Row], role: type[Role], *, name: str
) -> TableAlias[Alias[Row, Role], Row]:
    """Use `alias(Account, ManagerRole, name='manager')` for another table occurrence."""
    return TableAlias(Source(row, role, name))


class Condition[Scope](Protocol):
    """Both ordinary predicates and declared relationships supply join conditions."""

    def __predicate__(self) -> Predicate[Scope]: ...


@dataclass(frozen=True)
class Relationship(Generic[From, To]):
    """Unaliased join shorthand backed by the earlier checked relationship factory."""

    from_type: type[From]
    to_type: type[To]
    core: LegacyRelationship[From, To]

    def __predicate__(self) -> Predicate[From | To]:
        """Bind ordinary model roles for `join(Account, on=ENTRY_ACCOUNT)`."""
        return self.core.on(legacy_source(self.from_type), legacy_source(self.to_type))

    @overload
    def on[Left, Right](
        self, source: Table[Left, From], target: Table[Right, To]
    ) -> Predicate[Left | Right]: ...
    @overload
    def on[Left, Right](
        self, source: NullableAlias[Left, From], target: Table[Right, To]
    ) -> Predicate[Outer[Left] | Right]: ...
    @overload
    def on[Left, Right](
        self, source: Table[Left, From], target: NullableAlias[Right, To]
    ) -> Predicate[Left | Outer[Right]]: ...
    @overload
    def on[Left, Right](
        self, source: NullableAlias[Left, From], target: NullableAlias[Right, To]
    ) -> Predicate[Outer[Left] | Outer[Right]]: ...
    def on(
        self,
        source: Table[Any, From] | NullableAlias[Any, From],
        target: Table[Any, To] | NullableAlias[Any, To],
    ) -> Predicate[Any]:
        """Bind model or nullable alias roles, e.g. ENTRY_ACCOUNT.on(notes, Account).

        The overloads preserve nullable scope separately from the materialized
        model type. The legacy binder checks both models at runtime.
        """
        left = (
            source.source
            if isinstance(source, NullableAlias)
            else source.__source__().raw
        )
        right = (
            target.source
            if isinstance(target, NullableAlias)
            else target.__source__().raw
        )
        # The legacy binder reads only row_type, name, and token. Nullable sources
        # supply those same attributes, with a distinct nullable token.
        return self.core.on(
            cast("Source[Any, From]", left), cast("Source[Any, To]", right)
        )

    def ddl(self) -> str:
        """Reuse the prototype's scalar/composite FK fragment, not full schema planning."""
        return self.core.ddl()


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
    """Declare compatible domains once; use the relationship directly as a join ON."""
    return Relationship(
        source.owner,
        target.owner,
        legacy_relationship(source, target, enforced=enforced),
    )


@dataclass(frozen=True)
class Mapped(Generic[Result]):
    """Private materialization plan consumed by transaction fetch methods."""

    _run: Callable[[Connection], Awaitable[list[Result]]]

    async def _fetch(self, connection: Connection) -> list[Result]:
        return await self._run(connection)


class Select[Result](Protocol):
    """Executable result-only helper contract, e.g. Select[tuple[str, int]]."""

    async def _fetch(self, connection: Connection) -> list[Result]: ...


@dataclass(frozen=True)
class Query(Generic[Scope, Needed_co, State, Result]):
    """An immutable query with separate available and required source coordinates."""

    core: CoreQuery[Any, Any, *tuple[Any, ...]]
    decode: Callable[[tuple[object, ...]], Result]

    def where(
        self, condition: Predicate[Scope]
    ) -> Query[Scope, Needed_co, Ready, Result]:
        """Append a predicate from available sources and choose explicit row scope."""
        return Query[Scope, Needed_co, Ready, Result](
            self.core.where(condition), self.decode
        )

    def all(self) -> Query[Scope, Needed_co, Ready, Result]:
        """Permit an unfiltered query without dropping earlier conditions."""
        return Query[Scope, Needed_co, Ready, Result](self.core.all(), self.decode)

    @overload
    def project[Root, Required, *Projected](
        self, projection: Columns[Root, Required, *Projected]
    ) -> TupleQuery[Scope, Required, State, *Projected]: ...
    @overload
    def project[Root, Required, Value](
        self, projection: Projection[Root, Required, Value]
    ) -> Query[Scope, Required, State, Value]: ...
    @overload
    def project[Owner0, Value0](
        self, item0: Selectable[Owner0, Value0]
    ) -> Query[Scope, Owner0, State, Value0]: ...
    @overload
    def project[Owner0, Owner1, Value0, Value1](
        self, item0: Selectable[Owner0, Value0], item1: Selectable[Owner1, Value1]
    ) -> TupleQuery[Scope, Owner0 | Owner1, State, Value0, Value1]: ...
    @overload
    def project[Owner0, Owner1, Owner2, Value0, Value1, Value2](
        self,
        item0: Selectable[Owner0, Value0],
        item1: Selectable[Owner1, Value1],
        item2: Selectable[Owner2, Value2],
    ) -> TupleQuery[Scope, Owner0 | Owner1 | Owner2, State, Value0, Value1, Value2]: ...
    @overload
    def project[Owner0, Owner1, Owner2, Owner3, Value0, Value1, Value2, Value3](
        self,
        item0: Selectable[Owner0, Value0],
        item1: Selectable[Owner1, Value1],
        item2: Selectable[Owner2, Value2],
        item3: Selectable[Owner3, Value3],
    ) -> TupleQuery[
        Scope, Owner0 | Owner1 | Owner2 | Owner3, State, Value0, Value1, Value2, Value3
    ]: ...
    def project(
        self, *items: Selectable[Any, Any] | Projection[Any, Any, Any]
    ) -> Query[Any, Any, State, Any]:
        """Replace the selected result without changing FROM, joins, or filters."""
        _, selections, decode = _projection(items)
        if len(items) > 1 or isinstance(items[0], Columns):
            return TupleQuery[Any, Any, State, *tuple[Any, ...]](
                replace(self.core, selections=selections), decode
            )
        return Query(replace(self.core, selections=selections), decode)

    def join[OtherScope, Other: ReadRow](
        self, other: Table[OtherScope, Other], *, on: Condition[Scope | OtherScope]
    ) -> Query[Scope | OtherScope, Needed_co, State, Result]:
        """Add an explicit source without changing the selected result shape."""
        occurrence = other.__source__().raw
        if isinstance(occurrence, OuterSource):
            message = "Nullable sources require left_join"
            raise ModelError(message)
        # Core adds exactly this source. ty loses the phantom union during construction.
        return cast(
            "Query[Scope | OtherScope, Needed_co, State, Result]",
            Query(self.core.join(occurrence, on=on.__predicate__()), self.decode),
        )

    def left_join[OtherScope, Other: ReadRow](
        self,
        other: NullableAlias[OtherScope, Other],
        *,
        on: Condition[Scope | Outer[OtherScope]],
    ) -> Query[Scope | Outer[OtherScope], Needed_co, State, Result]:
        """Add a nullable source without changing nonnullable scopes already present."""
        # The core joins precisely this nullable token; ty loses the phantom union.
        return cast(
            "Query[Scope | Outer[OtherScope], Needed_co, State, Result]",
            Query(
                self.core.left_join(other.source, on=on.__predicate__()), self.decode
            ),
        )

    def map[Here, MappedResult](
        self: Query[Here, Here, Ready, Result],
        factory: Callable[[Result], MappedResult],
    ) -> Mapped[MappedResult]:
        """Map each complete result as one Python value, never as a SQL expression."""

        async def execute(connection: Connection) -> list[MappedResult]:
            return [factory(row) for row in await self._fetch(connection)]

        return Mapped(execute)

    async def _fetch[Here](
        self: Query[Here, Here, Ready, Result], connection: Connection
    ) -> list[Result]:
        """Execute only when every projected source is available and scope is chosen."""
        return [self.decode(row) for row in await self.core.fetch(connection)]


class TupleQuery(
    Query[Scope, Needed_co, State, tuple[*Values]],
    Generic[Scope, Needed_co, State, *Values],
):
    """A tuple result with exact positional constructor inputs.

    `select(Account.name, Account.id).all().into(Summary)` preserves callback
    inference without overloaded scalar/tuple fetch methods. The shared parent
    still supplies SQL execution and the result-only Select[tuple[...]] contract.
    """

    def where(
        self, condition: Predicate[Scope]
    ) -> TupleQuery[Scope, Needed_co, Ready, *Values]:
        """Keep tuple slots when choosing a filter."""
        # Required sources and slot decoders are unchanged; constructor inference loses Needed_co.
        return cast(
            "TupleQuery[Scope, Needed_co, Ready, *Values]",
            TupleQuery(self.core.where(condition), self.decode),
        )

    def all(self) -> TupleQuery[Scope, Needed_co, Ready, *Values]:
        """Keep tuple slots when allowing an unfiltered query."""
        # all changes readiness only, not the projection requirements.
        return cast(
            "TupleQuery[Scope, Needed_co, Ready, *Values]",
            TupleQuery(self.core.all(), self.decode),
        )

    def join[OtherScope, Other: ReadRow](
        self, other: Table[OtherScope, Other], *, on: Condition[Scope | OtherScope]
    ) -> TupleQuery[Scope | OtherScope, Needed_co, State, *Values]:
        """Extend source availability while keeping every projected slot."""
        joined = super().join(other, on=on)
        # The parent establishes the scope change; only the tuple-specific facade changes.
        return cast(
            "TupleQuery[Scope | OtherScope, Needed_co, State, *Values]",
            TupleQuery(joined.core, joined.decode),
        )

    def left_join[OtherScope, Other: ReadRow](
        self,
        other: NullableAlias[OtherScope, Other],
        *,
        on: Condition[Scope | Outer[OtherScope]],
    ) -> TupleQuery[Scope | Outer[OtherScope], Needed_co, State, *Values]:
        """Preserve optional result slots and the distinct nullable source scope."""
        joined = super().left_join(other, on=on)
        # The parent binds exactly this nullable source and preserves the decoders.
        return cast(
            "TupleQuery[Scope | Outer[OtherScope], Needed_co, State, *Values]",
            TupleQuery(joined.core, joined.decode),
        )

    def into[Here, MappedResult](
        self: TupleQuery[Here, Here, Ready, *Values],
        factory: Callable[[*Values], MappedResult],
    ) -> Mapped[MappedResult]:
        """Materialize a checked positional constructor after the query is executable.

        `into(lambda name, number: Summary(name=name, number=number))` also checks
        keyword labels with exact lambda input types. Unlike `map`, this unpacks
        the result tuple. It is terminal Python materialization, not a SQL value.
        """

        async def execute(connection: Connection) -> list[MappedResult]:
            return [factory(*row) for row in await self._fetch(connection)]

        return Mapped(execute)


def _projection(
    items: tuple[Selectable[Any, Any] | Projection[Any, Any, Any], ...],
) -> tuple[
    Source[Any, Any] | OuterSource[Any, Any],
    tuple[Selection[Any, Any], ...],
    Callable[[tuple[object, ...]], Any],
]:
    """Only overload implementations erase coordinates; every slot keeps its decoder."""
    if not items:
        message = "Select needs at least one projection"
        raise ModelError(message)
    if len(items) == 1 and isinstance(items[0], Projection):
        projected = items[0]
        return projected.source, projected.selections, projected.decode
    if any(isinstance(item, Projection) for item in items):
        message = "A projection bundle must be the only projection argument"
        raise ModelError(message)
    # The guard rejects mixed bundle/item calls after type erasure.
    scalars = cast("tuple[Selectable[Any, Any], ...]", items)
    slots = tuple(item.__selection__() for item in scalars)

    def decode(row: tuple[object, ...]) -> Any:
        return row[0] if len(slots) == 1 else row

    return slots[0].source, tuple(slot.selection for slot in slots), decode


@overload
def select[Root: ReadRow | Alias[Any, Any], Required, *Projected](
    projection: Columns[Root, Required, *Projected],
) -> TupleQuery[Root, Required, Unscoped, *Projected]: ...
@overload
def select[Root: ReadRow | Alias[Any, Any], Required, Result](
    projection: Projection[Root, Required, Result],
) -> Query[Root, Required, Unscoped, Result]: ...
@overload
def select[Scope: ReadRow | Alias[Any, Any], Result](
    item: Selectable[Scope, Result],
) -> Query[Scope, Scope, Unscoped, Result]: ...
@overload
def select[Scope: ReadRow | Alias[Any, Any], OtherScope, First, Second](
    item: Selectable[Scope, First], other: Selectable[OtherScope, Second]
) -> TupleQuery[Scope, Scope | OtherScope, Unscoped, First, Second]: ...
@overload
def select[Owner0: ReadRow | Alias[Any, Any], Owner1, Owner2, Value0, Value1, Value2](
    item0: Selectable[Owner0, Value0],
    item1: Selectable[Owner1, Value1],
    item2: Selectable[Owner2, Value2],
) -> TupleQuery[Owner0, Owner0 | Owner1 | Owner2, Unscoped, Value0, Value1, Value2]: ...
@overload
def select[
    Owner0: ReadRow | Alias[Any, Any],
    Owner1,
    Owner2,
    Owner3,
    Value0,
    Value1,
    Value2,
    Value3,
](
    item0: Selectable[Owner0, Value0],
    item1: Selectable[Owner1, Value1],
    item2: Selectable[Owner2, Value2],
    item3: Selectable[Owner3, Value3],
) -> TupleQuery[
    Owner0, Owner0 | Owner1 | Owner2 | Owner3, Unscoped, Value0, Value1, Value2, Value3
]: ...
def select(
    *items: Selectable[Any, Any] | Projection[Any, Any, Any],
) -> Query[Any, Any, Unscoped, Any]:
    """Select models or columns; the first item supplies FROM, not an implicit join.

    One item returns its value. Multiple items return a flat tuple. A projection
    can mention later joins, but cannot execute before those sources are present.
    """
    source, selections, decode = _projection(items)
    if isinstance(source, OuterSource):
        message = "Start from a nonnullable source, then project the outer column"
        raise ModelError(message)
    core = CoreQuery[Any, Any, *tuple[Any, ...]](source, selections=selections)
    if len(items) > 1 or isinstance(items[0], Columns):
        return TupleQuery[Any, Any, Unscoped, *tuple[Any, ...]](core, decode)
    return Query(core, decode)


@overload
def columns[Scope, Value](
    item: Selectable[Scope, Value],
) -> Columns[Scope, Scope, Value]: ...
@overload
def columns[Scope, OtherScope, First, Second](
    item: Selectable[Scope, First], other: Selectable[OtherScope, Second]
) -> Columns[Scope, Scope | OtherScope, First, Second]: ...
@overload
def columns[Owner0, Owner1, Owner2, Value0, Value1, Value2](
    item0: Selectable[Owner0, Value0],
    item1: Selectable[Owner1, Value1],
    item2: Selectable[Owner2, Value2],
) -> Columns[Owner0, Owner0 | Owner1 | Owner2, Value0, Value1, Value2]: ...
@overload
def columns[Owner0, Owner1, Owner2, Owner3, Value0, Value1, Value2, Value3](
    item0: Selectable[Owner0, Value0],
    item1: Selectable[Owner1, Value1],
    item2: Selectable[Owner2, Value2],
    item3: Selectable[Owner3, Value3],
) -> Columns[
    Owner0, Owner0 | Owner1 | Owner2 | Owner3, Value0, Value1, Value2, Value3
]: ...
def columns(*items: Selectable[Any, Any]) -> Columns[Any, Any, *tuple[Any, ...]]:
    """Start a reusable tuple projection; `.add` has no arity ceiling."""
    source, selections, _ = _projection(items)
    return Columns(source, selections, lambda row: row)


def composite[From: ReadRow, To: ReadRow](
    first: Relationship[From, To],
    second: Relationship[From, To],
    *rest: Relationship[From, To],
) -> Relationship[From, To]:
    """Keep composite pair validation while allowing the result directly in ON."""
    return Relationship(
        first.from_type,
        first.to_type,
        legacy_composite(first.core, second.core, *(edge.core for edge in rest)),
    )


def named_alias[Row: ReadRow, Name: LiteralString](
    row: type[Row], *, name: Name
) -> TableAlias[Alias[Row, Name], Row]:
    """Preserve direct literal names; broad LiteralString parameters lose identity."""
    return TableAlias(Source(row, name, name))
