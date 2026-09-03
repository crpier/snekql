"""PROTOTYPE: backend-specific typed facades over family-erased core carriers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, Self, cast


class Pending:
    """Application-constructed Table Model state."""


class Fetched:
    """Database-materialized Table Model state."""


class _Model[StateT, ReadT]:
    """Family-erased model implementation shared by both facades."""

    @classmethod
    def __owner_type__(cls) -> type[Self]:
        raise NotImplementedError

    @classmethod
    def __read_type__(cls) -> type[ReadT]:
        raise NotImplementedError


class SqliteModel[StateT, ReadT](_Model[StateT, ReadT]):
    """Nominal SQLite Table Model facade."""


class MariadbModel[StateT, ReadT](_Model[StateT, ReadT]):
    """Nominal MariaDB Table Model facade."""


class _ModelClass[OwnerT, ReadT](Protocol):
    """Connect a Pending Model class to its Fetched Model result."""

    @classmethod
    def __owner_type__(cls) -> type[OwnerT]: ...

    @classmethod
    def __read_type__(cls) -> type[ReadT]: ...


class _Insertable[OwnerT, ReadT](Protocol):
    """Connect one Pending Model instance to its owner and read types."""

    @classmethod
    def __owner_type__(cls) -> type[OwnerT]: ...

    @classmethod
    def __read_type__(cls) -> type[ReadT]: ...


class Column[OwnerT, ValueT]:
    """Model-owned projected column."""


class JoinOn[LeftT, RightT]:
    """Typed join condition between two Table Models."""


class ForeignKeyColumn[OwnerT, TargetT, ValueT](Column[OwnerT, ValueT]):
    """Column whose target model participates in join typing."""

    def references(
        self,
        target: Column[TargetT, ValueT],
    ) -> JoinOn[OwnerT, TargetT]:
        _ = target
        return JoinOn()


class _StoredSelect[ScopeBaseT, RowT](Protocol):
    """Stored select annotation branded by an allowed nominal model base."""

    def __scope_type__(self) -> ScopeBaseT: ...

    def __row_type__(self) -> RowT: ...


class _StoredWrite[OwnerBaseT, ResultT](Protocol):
    """Stored write annotation branded by an allowed nominal model base."""

    def __owner_type__(self) -> OwnerBaseT: ...

    def __result_type__(self) -> ResultT: ...


class SelectQuery[ScopeT, RowT]:
    """Family-erased select carrier."""

    def __scope_type__(self) -> ScopeT:
        raise NotImplementedError

    def __row_type__(self) -> RowT:
        raise NotImplementedError

    def join[NewOwnerT, NewReadT](
        self,
        model: _ModelClass[NewOwnerT, NewReadT],
        *,
        on: JoinOn[ScopeT, NewOwnerT] | JoinOn[NewOwnerT, ScopeT],
    ) -> SelectQuery[ScopeT | NewOwnerT, tuple[RowT, NewReadT]]:
        _ = model
        _ = on
        return cast(
            "SelectQuery[ScopeT | NewOwnerT, tuple[RowT, NewReadT]]",
            SelectQuery(),
        )


class InsertQuery[OwnerT, ReadT]:
    """Family-erased insert before a returning policy is chosen."""

    def returning(self) -> WriteQuery[OwnerT, ReadT]:
        return WriteQuery()


class WriteQuery[OwnerT, ResultT]:
    """Family-erased executable write carrier."""

    def __owner_type__(self) -> OwnerT:
        raise NotImplementedError

    def __result_type__(self) -> ResultT:
        raise NotImplementedError


type SqliteSelect[RowT] = _StoredSelect[SqliteModel[Any, Any], RowT]
type MariadbSelect[RowT] = _StoredSelect[MariadbModel[Any, Any], RowT]
type SqliteWrite[ResultT] = _StoredWrite[SqliteModel[Any, Any], ResultT]
type MariadbWrite[ResultT] = _StoredWrite[MariadbModel[Any, Any], ResultT]


class SqliteConfig:
    """SQLite runtime configuration facade."""


class MariadbConfig:
    """MariaDB runtime configuration facade."""


class SqliteTransaction:
    """Typed facade that delegates to the shared Transaction implementation."""

    async def fetch_all[RowT](
        self,
        query: _StoredSelect[SqliteModel[Any, Any], RowT],
    ) -> list[RowT]:
        raise NotImplementedError

    async def execute[ResultT](
        self,
        query: _StoredWrite[SqliteModel[Any, Any], ResultT],
    ) -> ResultT:
        raise NotImplementedError


class MariadbTransaction:
    """MariaDB copy of the typed Transaction facade."""

    async def fetch_all[RowT](
        self,
        query: _StoredSelect[MariadbModel[Any, Any], RowT],
    ) -> list[RowT]:
        raise NotImplementedError

    async def execute[ResultT](
        self,
        query: _StoredWrite[MariadbModel[Any, Any], ResultT],
    ) -> ResultT:
        raise NotImplementedError


class SqliteDatabase:
    """SQLite-specific declaration facade over the shared Database runtime."""

    @classmethod
    async def initialize(
        cls,
        config: SqliteConfig | None = None,
        *,
        database: Path | None = None,
    ) -> SqliteDatabase:
        _ = config
        _ = database
        return cls()

    def transaction(self) -> SqliteTransaction:
        return SqliteTransaction()


class MariadbDatabase:
    """MariaDB-specific declaration facade over the shared Database runtime."""

    @classmethod
    async def initialize(cls, config: MariadbConfig) -> MariadbDatabase:
        _ = config
        return cls()

    def transaction(self) -> MariadbTransaction:
        return MariadbTransaction()


class SqliteVerbs:
    """SQLite namespace declarations wrapping family-erased builder functions."""

    def select[OwnerT: SqliteModel[Any, Any], ReadT](
        self,
        model: _ModelClass[OwnerT, ReadT],
    ) -> SelectQuery[OwnerT, ReadT]:
        _ = model
        return SelectQuery()

    def project[OwnerT: SqliteModel[Any, Any], ValueT](
        self,
        column: Column[OwnerT, ValueT],
    ) -> SelectQuery[OwnerT, ValueT]:
        _ = column
        return SelectQuery()

    def insert[OwnerT: SqliteModel[Any, Any], ReadT](
        self,
        row: _Insertable[OwnerT, ReadT],
    ) -> InsertQuery[OwnerT, ReadT]:
        _ = row
        return InsertQuery()

    def update[OwnerT: SqliteModel[Any, Any], ReadT](
        self,
        model: _ModelClass[OwnerT, ReadT],
    ) -> WriteQuery[OwnerT, int]:
        _ = model
        raise NotImplementedError

    def delete[OwnerT: SqliteModel[Any, Any], ReadT](
        self,
        model: _ModelClass[OwnerT, ReadT],
    ) -> WriteQuery[OwnerT, int]:
        _ = model
        raise NotImplementedError

    def foreign_key[TargetT: SqliteModel[Any, Any], ValueT](
        self,
        target: Column[TargetT, ValueT],
    ) -> ForeignKeyColumn[Any, TargetT, ValueT]:
        _ = target
        return ForeignKeyColumn()

    def scaffold[OwnerT: SqliteModel[Any, Any]](
        self,
        models: list[type[OwnerT]],
    ) -> str:
        _ = models
        return ""


class MariadbVerbs:
    """MariaDB copy of the namespace declaration facade."""

    def select[OwnerT: MariadbModel[Any, Any], ReadT](
        self,
        model: _ModelClass[OwnerT, ReadT],
    ) -> SelectQuery[OwnerT, ReadT]:
        _ = model
        return SelectQuery()

    def project[OwnerT: MariadbModel[Any, Any], ValueT](
        self,
        column: Column[OwnerT, ValueT],
    ) -> SelectQuery[OwnerT, ValueT]:
        _ = column
        return SelectQuery()

    def insert[OwnerT: MariadbModel[Any, Any], ReadT](
        self,
        row: _Insertable[OwnerT, ReadT],
    ) -> InsertQuery[OwnerT, ReadT]:
        _ = row
        return InsertQuery()

    def update[OwnerT: MariadbModel[Any, Any], ReadT](
        self,
        model: _ModelClass[OwnerT, ReadT],
    ) -> WriteQuery[OwnerT, int]:
        _ = model
        raise NotImplementedError

    def delete[OwnerT: MariadbModel[Any, Any], ReadT](
        self,
        model: _ModelClass[OwnerT, ReadT],
    ) -> WriteQuery[OwnerT, int]:
        _ = model
        raise NotImplementedError

    def foreign_key[TargetT: MariadbModel[Any, Any], ValueT](
        self,
        target: Column[TargetT, ValueT],
    ) -> ForeignKeyColumn[Any, TargetT, ValueT]:
        _ = target
        return ForeignKeyColumn()

    def scaffold[OwnerT: MariadbModel[Any, Any]](
        self,
        models: list[type[OwnerT]],
    ) -> str:
        _ = models
        return ""


sqlite = SqliteVerbs()
mariadb = MariadbVerbs()
