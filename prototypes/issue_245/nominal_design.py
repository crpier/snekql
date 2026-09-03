"""PROTOTYPE: executable readiness encoded by nominal staged builder classes."""

from __future__ import annotations

from typing import Any, Protocol, Self, cast, overload


class Pending:
    """Application-constructed model state."""


class Fetched:
    """Database-materialized model state."""


class Model[StateT, ReadT]:
    """Minimal Table Model carrying owner and Fetched result witnesses."""

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


class _SelectShape[RowT]:
    """Select carrier implemented only by executable nominal stages."""

    def __row_type__(self) -> RowT:
        raise NotImplementedError


class SelectDraft[ScopeT, RowT]:
    """Select stage with neither `all()` nor `where()`."""

    def all(self) -> SelectReady[ScopeT, RowT]:
        return SelectReady()

    def where(self, predicate: Predicate[ScopeT]) -> SelectReady[ScopeT, RowT]:
        _ = predicate
        return SelectReady()

    @overload
    def join[NewOwnerT, NewReadT](
        self,
        model: ModelClass[NewOwnerT, NewReadT],
        *,
        on: JoinOn[ScopeT, NewOwnerT],
    ) -> SelectDraft[ScopeT | NewOwnerT, tuple[RowT, NewReadT]]: ...

    @overload
    def join[NewOwnerT, NewReadT](
        self,
        model: ModelClass[NewOwnerT, NewReadT],
        *,
        on: JoinOn[NewOwnerT, ScopeT],
    ) -> SelectDraft[ScopeT | NewOwnerT, tuple[RowT, NewReadT]]: ...

    def join(self, model: object, *, on: object) -> SelectDraft[Any, tuple[RowT, Any]]:
        _ = model
        _ = on
        return SelectDraft()


class SelectReady[ScopeT, RowT](_SelectShape[RowT]):
    """Executable select stage."""

    def all(self) -> Self:
        return self

    def where(self, predicate: Predicate[ScopeT]) -> Self:
        _ = predicate
        return self

    @overload
    def join[NewOwnerT, NewReadT](
        self,
        model: ModelClass[NewOwnerT, NewReadT],
        *,
        on: JoinOn[ScopeT, NewOwnerT],
    ) -> SelectReady[ScopeT | NewOwnerT, tuple[RowT, NewReadT]]: ...

    @overload
    def join[NewOwnerT, NewReadT](
        self,
        model: ModelClass[NewOwnerT, NewReadT],
        *,
        on: JoinOn[NewOwnerT, ScopeT],
    ) -> SelectReady[ScopeT | NewOwnerT, tuple[RowT, NewReadT]]: ...

    def join(self, model: object, *, on: object) -> SelectReady[Any, tuple[RowT, Any]]:
        _ = model
        _ = on
        return SelectReady()


class _WriteShape[ResultT]:
    """Write carrier implemented only by executable nominal stages."""

    def __result_type__(self) -> ResultT:
        raise NotImplementedError


class DeleteDraft[OwnerT, ReadT, ResultT]:
    """Unscoped delete stage."""

    def all(self) -> DeleteReady[OwnerT, ReadT, ResultT]:
        return DeleteReady()

    def where(
        self,
        predicate: Predicate[OwnerT],
    ) -> DeleteReady[OwnerT, ReadT, ResultT]:
        _ = predicate
        return DeleteReady()

    @overload
    def returning(self) -> DeleteDraft[OwnerT, ReadT, list[ReadT]]: ...

    @overload
    def returning[ValueT](
        self,
        column: Column[OwnerT, ValueT],
    ) -> DeleteDraft[OwnerT, ReadT, list[ValueT]]: ...

    def returning(self, column: object | None = None) -> object:
        _ = column
        return self


class DeleteReady[OwnerT, ReadT, ResultT](_WriteShape[ResultT]):
    """Executable delete stage."""

    def all(self) -> Self:
        return self

    def where(self, predicate: Predicate[OwnerT]) -> Self:
        _ = predicate
        return self

    @overload
    def returning(self) -> DeleteReady[OwnerT, ReadT, list[ReadT]]: ...

    @overload
    def returning[ValueT](
        self,
        column: Column[OwnerT, ValueT],
    ) -> DeleteReady[OwnerT, ReadT, list[ValueT]]: ...

    def returning(self, column: object | None = None) -> object:
        _ = column
        return self


class UpdateEmpty[OwnerT, ReadT, ResultT]:
    """Update stage with neither assignment nor row scope."""

    def set(
        self,
        assignment: Assignment[OwnerT],
    ) -> UpdateAssigned[OwnerT, ReadT, ResultT]:
        _ = assignment
        return UpdateAssigned()

    def where(
        self,
        predicate: Predicate[OwnerT],
    ) -> UpdateScoped[OwnerT, ReadT, ResultT]:
        _ = predicate
        return UpdateScoped()

    def all(self) -> UpdateScoped[OwnerT, ReadT, ResultT]:
        return UpdateScoped()

    @overload
    def returning(self) -> UpdateEmpty[OwnerT, ReadT, list[ReadT]]: ...

    @overload
    def returning[ValueT](
        self,
        column: Column[OwnerT, ValueT],
    ) -> UpdateEmpty[OwnerT, ReadT, list[ValueT]]: ...

    def returning(self, column: object | None = None) -> object:
        _ = column
        return self


class UpdateAssigned[OwnerT, ReadT, ResultT]:
    """Update stage with assignment but no row scope."""

    def set(self, assignment: Assignment[OwnerT]) -> Self:
        _ = assignment
        return self

    def where(
        self,
        predicate: Predicate[OwnerT],
    ) -> UpdateReady[OwnerT, ReadT, ResultT]:
        _ = predicate
        return UpdateReady()

    def all(self) -> UpdateReady[OwnerT, ReadT, ResultT]:
        return UpdateReady()

    @overload
    def returning(self) -> UpdateAssigned[OwnerT, ReadT, list[ReadT]]: ...

    @overload
    def returning[ValueT](
        self,
        column: Column[OwnerT, ValueT],
    ) -> UpdateAssigned[OwnerT, ReadT, list[ValueT]]: ...

    def returning(self, column: object | None = None) -> object:
        _ = column
        return self


class UpdateScoped[OwnerT, ReadT, ResultT]:
    """Update stage with row scope but no assignment."""

    def set(
        self,
        assignment: Assignment[OwnerT],
    ) -> UpdateReady[OwnerT, ReadT, ResultT]:
        _ = assignment
        return UpdateReady()

    def where(self, predicate: Predicate[OwnerT]) -> Self:
        _ = predicate
        return self

    def all(self) -> Self:
        return self

    @overload
    def returning(self) -> UpdateScoped[OwnerT, ReadT, list[ReadT]]: ...

    @overload
    def returning[ValueT](
        self,
        column: Column[OwnerT, ValueT],
    ) -> UpdateScoped[OwnerT, ReadT, list[ValueT]]: ...

    def returning(self, column: object | None = None) -> object:
        _ = column
        return self


class UpdateReady[OwnerT, ReadT, ResultT](_WriteShape[ResultT]):
    """Executable update stage with assignment and row scope."""

    def set(self, assignment: Assignment[OwnerT]) -> Self:
        _ = assignment
        return self

    def where(self, predicate: Predicate[OwnerT]) -> Self:
        _ = predicate
        return self

    def all(self) -> Self:
        return self

    @overload
    def returning(self) -> UpdateReady[OwnerT, ReadT, list[ReadT]]: ...

    @overload
    def returning[ValueT](
        self,
        column: Column[OwnerT, ValueT],
    ) -> UpdateReady[OwnerT, ReadT, list[ValueT]]: ...

    def returning(self, column: object | None = None) -> object:
        _ = column
        return self


type Select[RowT] = _SelectShape[RowT]
type Write[ResultT] = _WriteShape[ResultT]


class Transaction:
    """Query Runtime sees only executable carriers."""

    async def fetch_all[RowT](self, query: _SelectShape[RowT]) -> list[RowT]:
        _ = query
        raise NotImplementedError

    async def execute[ResultT](self, query: _WriteShape[ResultT]) -> ResultT:
        _ = query
        raise NotImplementedError


def select[OwnerT, ReadT](
    model: ModelClass[OwnerT, ReadT],
) -> SelectDraft[OwnerT, ReadT]:
    """Start an incomplete nominal select stage."""

    _ = model
    return cast("SelectDraft[OwnerT, ReadT]", SelectDraft())


def delete[OwnerT, ReadT](
    model: ModelClass[OwnerT, ReadT],
) -> DeleteDraft[OwnerT, ReadT, int]:
    """Start an unscoped nominal delete stage."""

    _ = model
    return cast("DeleteDraft[OwnerT, ReadT, int]", DeleteDraft())


def update[OwnerT, ReadT](
    model: ModelClass[OwnerT, ReadT],
) -> UpdateEmpty[OwnerT, ReadT, int]:
    """Start an empty nominal update stage."""

    _ = model
    return cast("UpdateEmpty[OwnerT, ReadT, int]", UpdateEmpty())
