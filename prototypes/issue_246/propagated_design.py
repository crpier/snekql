"""PROTOTYPE: one private family witness propagated through typed carriers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Protocol, Self, cast

type SqliteFamily = Literal["sqlite"]
type MariadbFamily = Literal["mariadb"]


class Pending:
    """Application-constructed Table Model state."""


class Fetched:
    """Database-materialized Table Model state."""


class _Model[FamilyT, StateT, ReadT]:
    """Shared model implementation carrying an erased family witness."""

    @classmethod
    def __family_type__(cls) -> FamilyT:
        raise NotImplementedError

    @classmethod
    def __owner_type__(cls) -> type[Self]:
        raise NotImplementedError

    @classmethod
    def __read_type__(cls) -> type[ReadT]:
        raise NotImplementedError


class SqliteModel[StateT, ReadT](_Model[SqliteFamily, StateT, ReadT]):
    """SQLite Model keeps the current two public type arguments."""


class MariadbModel[StateT, ReadT](_Model[MariadbFamily, StateT, ReadT]):
    """MariaDB Model keeps the current two public type arguments."""


class _ModelClass[FamilyT, OwnerT, ReadT](Protocol):
    """Connect a model class to its family, owner, and fetched result."""

    @classmethod
    def __family_type__(cls) -> FamilyT: ...

    @classmethod
    def __owner_type__(cls) -> type[OwnerT]: ...

    @classmethod
    def __read_type__(cls) -> type[ReadT]: ...


class _Insertable[FamilyT, ReadT](Protocol):
    """Connect one Pending Model instance to its family and fetched result."""

    @classmethod
    def __family_type__(cls) -> FamilyT: ...

    @classmethod
    def __read_type__(cls) -> type[ReadT]: ...


class Column[FamilyT, OwnerT, ValueT]:
    """Projected column carrying its owning model's family."""


class JoinOn[FamilyT, LeftT, RightT]:
    """Join condition whose two models belong to one family."""


class ForeignKeyColumn[FamilyT, OwnerT, TargetT, ValueT](
    Column[FamilyT, OwnerT, ValueT]
):
    """Foreign key constrained to a target from the same family."""

    def references(
        self,
        target: Column[FamilyT, TargetT, ValueT],
    ) -> JoinOn[FamilyT, OwnerT, TargetT]:
        _ = target
        return JoinOn()


class SelectQuery[FamilyT, ScopeT, RowT]:
    """Select carrier that keeps family independent from result shape."""

    def join[NewOwnerT, NewReadT](
        self,
        model: _ModelClass[FamilyT, NewOwnerT, NewReadT],
        *,
        on: JoinOn[FamilyT, ScopeT, NewOwnerT] | JoinOn[FamilyT, NewOwnerT, ScopeT],
    ) -> SelectQuery[FamilyT, ScopeT | NewOwnerT, tuple[RowT, NewReadT]]:
        _ = model
        _ = on
        return cast(
            "SelectQuery[FamilyT, ScopeT | NewOwnerT, tuple[RowT, NewReadT]]",
            SelectQuery(),
        )


class InsertQuery[FamilyT, ReadT]:
    """Insert carrier whose family survives choosing returning policy."""

    def returning(self) -> WriteQuery[FamilyT, ReadT]:
        return WriteQuery()


class WriteQuery[FamilyT, ResultT]:
    """Executable write carrying family and result independently."""


type SqliteSelect[RowT] = SelectQuery[SqliteFamily, Any, RowT]
type MariadbSelect[RowT] = SelectQuery[MariadbFamily, Any, RowT]
type SqliteWrite[ResultT] = WriteQuery[SqliteFamily, ResultT]
type MariadbWrite[ResultT] = WriteQuery[MariadbFamily, ResultT]


class Config[FamilyT]:
    """Backend configuration carrying the same family witness as Database."""


class SqliteConfig(Config[SqliteFamily]):
    """SQLite configuration."""


class MariadbConfig(Config[MariadbFamily]):
    """MariaDB configuration."""


class Transaction[FamilyT]:
    """One runtime interface for either family."""

    async def fetch_all[ScopeT, RowT](
        self,
        query: SelectQuery[FamilyT, ScopeT, RowT],
    ) -> list[RowT]:
        raise NotImplementedError

    async def execute[ResultT](
        self,
        query: WriteQuery[FamilyT, ResultT],
    ) -> ResultT:
        raise NotImplementedError


class _Database[FamilyT]:
    """Shared Database implementation beneath namespace construction facades."""

    def transaction(self) -> Transaction[FamilyT]:
        raise NotImplementedError


class SqliteDatabase(_Database[SqliteFamily]):
    """SQLite construction policy, including its path convenience form."""

    @classmethod
    async def initialize(
        cls,
        config: SqliteConfig | None = None,
        *,
        database: Path | None = None,
    ) -> SqliteDatabase:
        _ = config
        _ = database
        raise NotImplementedError


class MariadbDatabase(_Database[MariadbFamily]):
    """MariaDB construction policy requires MariaDB configuration."""

    @classmethod
    async def initialize(cls, config: MariadbConfig) -> MariadbDatabase:
        _ = config
        raise NotImplementedError


class Verbs[FamilyT]:
    """One namespace verb interface specialized by a private family witness."""

    def select[OwnerT, ReadT](
        self,
        model: _ModelClass[FamilyT, OwnerT, ReadT],
    ) -> SelectQuery[FamilyT, OwnerT, ReadT]:
        _ = model
        raise NotImplementedError

    def project[OwnerT, ValueT](
        self,
        column: Column[FamilyT, OwnerT, ValueT],
    ) -> SelectQuery[FamilyT, OwnerT, ValueT]:
        _ = column
        raise NotImplementedError

    def insert[ReadT](
        self,
        row: _Insertable[FamilyT, ReadT],
    ) -> InsertQuery[FamilyT, ReadT]:
        _ = row
        raise NotImplementedError

    def update[OwnerT, ReadT](
        self,
        model: _ModelClass[FamilyT, OwnerT, ReadT],
    ) -> WriteQuery[FamilyT, int]:
        _ = model
        raise NotImplementedError

    def delete[OwnerT, ReadT](
        self,
        model: _ModelClass[FamilyT, OwnerT, ReadT],
    ) -> WriteQuery[FamilyT, int]:
        _ = model
        raise NotImplementedError

    def foreign_key[OwnerT, TargetT, ValueT](
        self,
        target: Column[FamilyT, TargetT, ValueT],
    ) -> ForeignKeyColumn[FamilyT, OwnerT, TargetT, ValueT]:
        _ = target
        raise NotImplementedError

    def scaffold(
        self,
        models: list[type[_Model[FamilyT, Any, Any]]],
    ) -> str:
        _ = models
        return ""


sqlite = Verbs[SqliteFamily]()
mariadb = Verbs[MariadbFamily]()
