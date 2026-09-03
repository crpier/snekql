"""PROTOTYPE: executable readiness as one private covariant typestate coordinate."""

from __future__ import annotations

from typing import Any, Protocol, Self, cast, overload


class Pending:
    """Application-constructed model state."""


class Fetched:
    """Database-materialized model state."""


class _Incomplete:
    """Typing-only marker for a query that Query Compilation must reject."""


class _Executable:
    """Typing-only marker accepted by Query Runtime and public query aliases."""


class _UpdateEmpty(_Incomplete):
    """Update has neither assignment nor row scope."""


class _UpdateAssigned(_Incomplete):
    """Update has an assignment but no row scope."""


class _UpdateScoped(_Incomplete):
    """Update has row scope but no assignment."""


class _UpdateReady(_Executable):
    """Update has both an assignment and row scope."""


class Model[StateT, ReadT]:
    """Minimal Table Model carrying its Fetched result witness."""

    @classmethod
    def __owner_type__(cls) -> type[Self]:
        raise NotImplementedError

    @classmethod
    def __owner_invariant__(cls, owner: Self) -> Self:
        raise NotImplementedError

    @classmethod
    def __read_type__(cls) -> type[ReadT]:
        raise NotImplementedError


class ModelClass[OwnerT, ReadT](Protocol):
    """Connect one model class to its Pending owner and Fetched result."""

    @classmethod
    def __owner_type__(cls) -> type[OwnerT]: ...

    @classmethod
    def __owner_invariant__(cls, owner: OwnerT) -> OwnerT: ...

    @classmethod
    def __read_type__(cls) -> type[ReadT]: ...


class Predicate[OwnerT]:
    """Owner-scoped predicate placeholder."""


class Assignment[OwnerT]:
    """Owner-scoped assignment placeholder."""


class JoinOn[LeftT, RightT]:
    """Join condition placeholder."""


class Column[OwnerT, ValueT]:
    """Typed column operations needed by readiness probes."""

    def eq(self, value: ValueT) -> Predicate[OwnerT]:
        _ = value
        return Predicate()

    def references[TargetT](
        self, target: Column[TargetT, ValueT]
    ) -> JoinOn[OwnerT, TargetT]:
        _ = target
        return JoinOn()

    def to(self, value: ValueT) -> Assignment[OwnerT]:
        _ = value
        return Assignment()


class _SelectShape[RowT, ReadinessT]:
    """Private select carrier separating result shape from readiness."""

    def __row_type__(self) -> RowT:
        raise NotImplementedError

    def __readiness_type__(self) -> ReadinessT:
        raise NotImplementedError


class SelectQuery[ScopeT, RowT, ReadinessT](_SelectShape[RowT, ReadinessT]):
    """One select builder; fluent transitions change only private readiness."""

    def all(self) -> SelectQuery[ScopeT, RowT, _Executable]:
        return cast("SelectQuery[ScopeT, RowT, _Executable]", self)

    def where(
        self, predicate: Predicate[ScopeT]
    ) -> SelectQuery[ScopeT, RowT, _Executable]:
        _ = predicate
        return cast("SelectQuery[ScopeT, RowT, _Executable]", self)

    @overload
    def join[NewOwnerT, NewReadT](
        self,
        model: ModelClass[NewOwnerT, NewReadT],
        *,
        on: JoinOn[ScopeT, NewOwnerT],
    ) -> SelectQuery[ScopeT | NewOwnerT, tuple[RowT, NewReadT], ReadinessT]: ...

    @overload
    def join[NewOwnerT, NewReadT](
        self,
        model: ModelClass[NewOwnerT, NewReadT],
        *,
        on: JoinOn[NewOwnerT, ScopeT],
    ) -> SelectQuery[ScopeT | NewOwnerT, tuple[RowT, NewReadT], ReadinessT]: ...

    def join(
        self,
        model: object,
        *,
        on: object,
    ) -> SelectQuery[Any, tuple[RowT, Any], ReadinessT]:
        _ = model
        _ = on
        return cast(
            "SelectQuery[Any, tuple[RowT, Any], ReadinessT]",
            self,
        )


class _WriteShape[ResultT, ReadinessT]:
    """Private write carrier accepted only at executable readiness."""

    def __result_type__(self) -> ResultT:
        raise NotImplementedError

    def __readiness_type__(self) -> ReadinessT:
        raise NotImplementedError


class DeleteQuery[OwnerT, ReadT, ResultT, ReadinessT](_WriteShape[ResultT, ReadinessT]):
    """Delete carries one unscoped/executable readiness coordinate."""

    def all(self) -> DeleteQuery[OwnerT, ReadT, ResultT, _Executable]:
        return cast("DeleteQuery[OwnerT, ReadT, ResultT, _Executable]", self)

    def where(
        self,
        predicate: Predicate[OwnerT],
    ) -> DeleteQuery[OwnerT, ReadT, ResultT, _Executable]:
        _ = predicate
        return cast("DeleteQuery[OwnerT, ReadT, ResultT, _Executable]", self)

    @overload
    def returning(self) -> DeleteQuery[OwnerT, ReadT, list[ReadT], ReadinessT]: ...

    @overload
    def returning[ValueT](
        self,
        column: Column[OwnerT, ValueT],
    ) -> DeleteQuery[OwnerT, ReadT, list[ValueT], ReadinessT]: ...

    def returning(self, column: object | None = None) -> object:
        _ = column
        return self


class UpdateQuery[OwnerT, ReadT, ResultT, ReadinessT](_WriteShape[ResultT, ReadinessT]):
    """Update's four-state automaton stays in one private builder coordinate."""

    @overload
    def set(
        self: UpdateQuery[OwnerT, ReadT, ResultT, _UpdateEmpty],
        assignment: Assignment[OwnerT],
    ) -> UpdateQuery[OwnerT, ReadT, ResultT, _UpdateAssigned]: ...

    @overload
    def set(
        self: UpdateQuery[OwnerT, ReadT, ResultT, _UpdateScoped],
        assignment: Assignment[OwnerT],
    ) -> UpdateQuery[OwnerT, ReadT, ResultT, _UpdateReady]: ...

    @overload
    def set(
        self: UpdateQuery[OwnerT, ReadT, ResultT, _UpdateAssigned],
        assignment: Assignment[OwnerT],
    ) -> UpdateQuery[OwnerT, ReadT, ResultT, _UpdateAssigned]: ...

    @overload
    def set(
        self: UpdateQuery[OwnerT, ReadT, ResultT, _UpdateReady],
        assignment: Assignment[OwnerT],
    ) -> UpdateQuery[OwnerT, ReadT, ResultT, _UpdateReady]: ...

    def set(self, assignment: Assignment[OwnerT]) -> object:
        _ = assignment
        return self

    @overload
    def where(
        self: UpdateQuery[OwnerT, ReadT, ResultT, _UpdateEmpty],
        predicate: Predicate[OwnerT],
    ) -> UpdateQuery[OwnerT, ReadT, ResultT, _UpdateScoped]: ...

    @overload
    def where(
        self: UpdateQuery[OwnerT, ReadT, ResultT, _UpdateAssigned],
        predicate: Predicate[OwnerT],
    ) -> UpdateQuery[OwnerT, ReadT, ResultT, _UpdateReady]: ...

    @overload
    def where(
        self: UpdateQuery[OwnerT, ReadT, ResultT, _UpdateScoped],
        predicate: Predicate[OwnerT],
    ) -> UpdateQuery[OwnerT, ReadT, ResultT, _UpdateScoped]: ...

    @overload
    def where(
        self: UpdateQuery[OwnerT, ReadT, ResultT, _UpdateReady],
        predicate: Predicate[OwnerT],
    ) -> UpdateQuery[OwnerT, ReadT, ResultT, _UpdateReady]: ...

    def where(self, predicate: Predicate[OwnerT]) -> object:
        _ = predicate
        return self

    @overload
    def all(
        self: UpdateQuery[OwnerT, ReadT, ResultT, _UpdateEmpty],
    ) -> UpdateQuery[OwnerT, ReadT, ResultT, _UpdateScoped]: ...

    @overload
    def all(
        self: UpdateQuery[OwnerT, ReadT, ResultT, _UpdateAssigned],
    ) -> UpdateQuery[OwnerT, ReadT, ResultT, _UpdateReady]: ...

    @overload
    def all(
        self: UpdateQuery[OwnerT, ReadT, ResultT, _UpdateScoped],
    ) -> UpdateQuery[OwnerT, ReadT, ResultT, _UpdateScoped]: ...

    @overload
    def all(
        self: UpdateQuery[OwnerT, ReadT, ResultT, _UpdateReady],
    ) -> UpdateQuery[OwnerT, ReadT, ResultT, _UpdateReady]: ...

    def all(self) -> object:
        return self

    @overload
    def returning(self) -> UpdateQuery[OwnerT, ReadT, list[ReadT], ReadinessT]: ...

    @overload
    def returning[ValueT](
        self,
        column: Column[OwnerT, ValueT],
    ) -> UpdateQuery[OwnerT, ReadT, list[ValueT], ReadinessT]: ...

    def returning(self, column: object | None = None) -> object:
        _ = column
        return self


type _ExecutableSelect[RowT] = _SelectShape[RowT, _Executable]
type _ExecutableWrite[ResultT] = _WriteShape[ResultT, _Executable]
type Select[RowT] = _ExecutableSelect[RowT]
type Write[ResultT] = _ExecutableWrite[ResultT]


class Transaction:
    """Query Runtime consumes executable carriers, never concrete builders."""

    async def fetch_all[RowT](self, query: _ExecutableSelect[RowT]) -> list[RowT]:
        _ = query
        raise NotImplementedError

    async def execute[ResultT](self, query: _ExecutableWrite[ResultT]) -> ResultT:
        _ = query
        raise NotImplementedError


def select[OwnerT, ReadT](
    model: ModelClass[OwnerT, ReadT],
) -> SelectQuery[OwnerT, ReadT, _Incomplete]:
    """Start a guaranteed-incomplete select."""

    _ = model
    return cast("SelectQuery[OwnerT, ReadT, _Incomplete]", SelectQuery())


def delete[OwnerT, ReadT](
    model: ModelClass[OwnerT, ReadT],
) -> DeleteQuery[OwnerT, ReadT, int, _Incomplete]:
    """Start a guaranteed-unscoped delete."""

    _ = model
    return cast(
        "DeleteQuery[OwnerT, ReadT, int, _Incomplete]",
        DeleteQuery(),
    )


def update[OwnerT, ReadT](
    model: ModelClass[OwnerT, ReadT],
) -> UpdateQuery[OwnerT, ReadT, int, _UpdateEmpty]:
    """Start an update with neither assignment nor row scope."""

    _ = model
    return cast(
        "UpdateQuery[OwnerT, ReadT, int, _UpdateEmpty]",
        UpdateQuery(),
    )
