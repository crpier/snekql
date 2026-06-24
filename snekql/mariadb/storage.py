"""MariaDB storage declarations for table models."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import EllipsisType
from typing import TYPE_CHECKING, Any, cast, overload

from snekql._query_state import require_column_model
from snekql.expressions import Comparable
from snekql.storage import (
    Attr,
    AttrConfig,
    CurrentTimestamp,
    FKAttr,
    ForeignKey,
    PendingGeneration,
    build_attr,
)

if TYPE_CHECKING:
    from snekql._dialect_expr import CompileCtx
    from snekql.model import Table


def _json_path_literal(path: str) -> str:
    """Render a JSON path as a single-quoted SQL string literal.

    Paths are developer-provided constants (``"$.age"``); single quotes are
    doubled so a literal renders safely inside the ``JSON_EXTRACT`` call.
    """

    escaped = path.replace("'", "''")
    return f"'{escaped}'"


@dataclass(frozen=True)
class _JsonExtractInt[OwnerT](Comparable[OwnerT, int]):
    """``JSON_EXTRACT(col, path)`` typed as an ``int`` (ADR 0004 open-AST seam).

    The first dialect-specific operator: it lives entirely in the MariaDB
    namespace and reaches the core only through the structural protocols.

    * ``Comparable[OwnerT, int]`` gives it the comparison surface (``.gt(18)``)
      typed to ``int``, so it works as a ``WHERE`` operand.
    * ``__owner_model__`` / ``__compile_sql__`` satisfy ``SqlCompilable`` (the
      operand-render seam).
    * ``__compile_select_sql__`` / ``__decode__`` additionally satisfy
      ``DialectSelectable[int]`` (the projection seam), so it can be projected
      and Materialized to an ``int`` without the core naming this class.
    """

    column: Attr[Any, Any, Any, Any, Any]
    path: str

    def __owner_model__(self) -> type[Table[Any]]:
        return require_column_model(self.column)

    def __compile_sql__(self, ctx: CompileCtx) -> str:
        return f"JSON_EXTRACT({ctx.render_column(self.column)}, {_json_path_literal(self.path)})"

    def __compile_select_sql__(self, ctx: CompileCtx) -> str:
        return self.__compile_sql__(ctx)

    def __decode__(self, raw: object) -> int:
        # MariaDB returns JSON scalars as text (or bytes from the driver); the
        # leaf owns this raw->typed conversion.
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode()
        return int(cast("str | int | float", raw))


class JsonAttr[
    WriteOwnerT,
    LoadedOwnerT,
    OwnerT,
    WriteT,
    ReadValueT,
    SetValueT = WriteT,
](
    FKAttr[WriteOwnerT, LoadedOwnerT, OwnerT, WriteT, ReadValueT, Any, SetValueT],
):
    """MariaDB JSON column descriptor carrying the JSON path operators.

    A field declared ``profile: User.JsonCol[...]`` resolves to this subtype, so
    ``json_extract_int`` is visible on JSON columns and nowhere else. Attaching
    the operator to the column subtype -- rather than the core ``Attr`` -- is the
    type-safety lever (ADR 0003 per-namespace columns + ADR 0004 open AST): the
    operator scopes to exactly the columns that support it.
    """

    def json_extract_int(self, path: str) -> _JsonExtractInt[OwnerT]:
        """Extract an integer at ``path`` from this JSON column.

        Returns a dialect expression usable as a ``WHERE`` operand
        (``profile.json_extract_int("$.age").gt(18)``) and as a typed ``int``
        ``SELECT`` projection.
        """

        return _JsonExtractInt(column=self, path=path)


class Integer:
    """MariaDB integer column declaration for table model fields.

    >>> class User[S = Pending](Model[S, "User[Fetched]"]):
    ...     id: User.GenCol[int] = Integer(primary_key=True, default=PENDING_GENERATION)
    """

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        auto_increment: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: PendingGeneration,
    ) -> Attr[Any, Any, Any, T | PendingGeneration, T]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        auto_increment: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: type[CurrentTimestamp],
    ) -> Attr[Any, Any, Any, T | PendingGeneration, T]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        auto_increment: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: None,
    ) -> Attr[Any, Any, Any, T | None, T | None, object]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        auto_increment: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: T,
    ) -> Attr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        auto_increment: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default_factory: Callable[[], T],
    ) -> Attr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__(
        cls,
        *,
        primary_key: bool = False,
        auto_increment: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any: ...

    def __new__(  # noqa: PLR0913
        cls,
        *,
        primary_key: bool = False,
        auto_increment: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return build_attr(
            AttrConfig(
                auto_increment=auto_increment,
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                primary_key=primary_key,
                unique=unique,
                sqlite_storage_class="INTEGER",
                storage_type_name="Integer",
            ),
        )


class Real:
    """MariaDB real-number column declaration for float-like model values."""

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: PendingGeneration,
    ) -> Attr[Any, Any, Any, T | PendingGeneration, T]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: type[CurrentTimestamp],
    ) -> Attr[Any, Any, Any, T | PendingGeneration, T]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: None,
    ) -> Attr[Any, Any, Any, T | None, T | None, object]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: T,
    ) -> Attr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default_factory: Callable[[], T],
    ) -> Attr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__(
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any: ...

    def __new__(
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return build_attr(
            AttrConfig(
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                primary_key=primary_key,
                unique=unique,
                sqlite_storage_class="REAL",
                storage_type_name="Real",
            ),
        )


class Text:
    """MariaDB text column declaration for string model values."""

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: PendingGeneration,
    ) -> Attr[Any, Any, Any, T | PendingGeneration, T]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: type[CurrentTimestamp],
    ) -> Attr[Any, Any, Any, T | PendingGeneration, T]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: None,
    ) -> Attr[Any, Any, Any, T | None, T | None, object]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: T,
    ) -> Attr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default_factory: Callable[[], T],
    ) -> Attr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__(
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any: ...

    def __new__(
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return build_attr(
            AttrConfig(
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                primary_key=primary_key,
                unique=unique,
                sqlite_storage_class="TEXT",
                storage_type_name="Text",
            ),
        )


class Blob:
    """MariaDB blob column declaration for bytes model values."""

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: PendingGeneration,
    ) -> Attr[Any, Any, Any, T | PendingGeneration, T]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: type[CurrentTimestamp],
    ) -> Attr[Any, Any, Any, T | PendingGeneration, T]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: None,
    ) -> Attr[Any, Any, Any, T | None, T | None, object]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: T,
    ) -> Attr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default_factory: Callable[[], T],
    ) -> Attr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__(
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any: ...

    def __new__(
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return build_attr(
            AttrConfig(
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                primary_key=primary_key,
                unique=unique,
                sqlite_storage_class="BLOB",
                storage_type_name="Blob",
            ),
        )


class Json:
    """MariaDB JSON column declaration for JSON-compatible model values.

    Builds a :class:`JsonAttr` so the runtime descriptor carries the JSON path
    operators; a field annotated ``Model.JsonCol[...]`` makes them visible to the
    type checker on JSON columns only.
    """

    @overload
    def __new__[T](
        cls,
        *,
        nullable: bool | None = None,
        unique: bool = False,
        default: T,
    ) -> JsonAttr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__[T](
        cls,
        *,
        nullable: bool | None = None,
        unique: bool = False,
        default_factory: Callable[[], T],
    ) -> JsonAttr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__(
        cls,
        *,
        nullable: bool | None = None,
        unique: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any: ...

    def __new__(
        cls,
        *,
        nullable: bool | None = None,
        unique: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return JsonAttr[Any, Any, Any, Any, Any](
            AttrConfig(
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                unique=unique,
                sqlite_storage_class="TEXT",
                storage_type_name="Json",
            ),
        )


class Boolean:
    """MariaDB boolean column declaration for bool model values."""

    @overload
    def __new__[T](
        cls,
        *,
        nullable: bool | None = None,
        unique: bool = False,
        default: PendingGeneration,
    ) -> Attr[Any, Any, Any, T | PendingGeneration, T]: ...

    @overload
    def __new__[T](
        cls,
        *,
        nullable: bool | None = None,
        unique: bool = False,
        default: type[CurrentTimestamp],
    ) -> Attr[Any, Any, Any, T | PendingGeneration, T]: ...

    @overload
    def __new__[T](
        cls,
        *,
        nullable: bool | None = None,
        unique: bool = False,
        default: None,
    ) -> Attr[Any, Any, Any, T | None, T | None, object]: ...

    @overload
    def __new__[T](
        cls,
        *,
        nullable: bool | None = None,
        unique: bool = False,
        default: T,
    ) -> Attr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__[T](
        cls,
        *,
        nullable: bool | None = None,
        unique: bool = False,
        default_factory: Callable[[], T],
    ) -> Attr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__(
        cls,
        *,
        nullable: bool | None = None,
        unique: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any: ...

    def __new__(
        cls,
        *,
        nullable: bool | None = None,
        unique: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return build_attr(
            AttrConfig(
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                unique=unique,
                sqlite_storage_class="INTEGER",
                storage_type_name="Boolean",
            ),
        )


class DateTime:
    """MariaDB datetime column declaration for timezone-aware datetimes."""

    @overload
    def __new__[T](
        cls,
        *,
        nullable: bool | None = None,
        unique: bool = False,
        default: PendingGeneration,
    ) -> Attr[Any, Any, Any, T | PendingGeneration, T]: ...

    @overload
    def __new__[T](
        cls,
        *,
        nullable: bool | None = None,
        unique: bool = False,
        default: type[CurrentTimestamp],
    ) -> Attr[Any, Any, Any, T | PendingGeneration, T]: ...

    @overload
    def __new__[T](
        cls,
        *,
        nullable: bool | None = None,
        unique: bool = False,
        default: None,
    ) -> Attr[Any, Any, Any, T | None, T | None, object]: ...

    @overload
    def __new__[T](
        cls,
        *,
        nullable: bool | None = None,
        unique: bool = False,
        default: T,
    ) -> Attr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__[T](
        cls,
        *,
        nullable: bool | None = None,
        unique: bool = False,
        default_factory: Callable[[], T],
    ) -> Attr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__(
        cls,
        *,
        nullable: bool | None = None,
        unique: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any: ...

    def __new__(
        cls,
        *,
        nullable: bool | None = None,
        unique: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return build_attr(
            AttrConfig(
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                unique=unique,
                sqlite_storage_class="TEXT",
                storage_type_name="DateTime",
            ),
        )


class Uuid:
    """MariaDB native ``UUID`` column declaration for ``uuid.UUID`` values.

    The native storage primitive for UUIDs (MariaDB 10.7+); the logical type is
    the field annotation (``Col[uuid.UUID]``). The driver exchanges UUID values
    as their string form, so encoding/decoding runs through the shared pydantic
    scalar codec -- no dedicated native codec. To store a UUID as raw bytes
    instead, use ``Blob()`` with a ``Col[uuid.UUID]`` annotation.

    >>> class User[S = Pending](Model[S, "User[Fetched]"]):
    ...     id: User.Col[uuid.UUID] = Uuid(primary_key=True, default_factory=uuid4)
    """

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: PendingGeneration,
    ) -> Attr[Any, Any, Any, T | PendingGeneration, T]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: type[CurrentTimestamp],
    ) -> Attr[Any, Any, Any, T | PendingGeneration, T]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: None,
    ) -> Attr[Any, Any, Any, T | None, T | None, object]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: T,
    ) -> Attr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default_factory: Callable[[], T],
    ) -> Attr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__(
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any: ...

    def __new__(
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return build_attr(
            AttrConfig(
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                primary_key=primary_key,
                unique=unique,
                sqlite_storage_class="TEXT",
                storage_type_name="Uuid",
            ),
        )


__all__ = [
    "Blob",
    "Boolean",
    "CurrentTimestamp",
    "DateTime",
    "ForeignKey",
    "Integer",
    "Json",
    "JsonAttr",
    "Real",
    "Text",
    "Uuid",
]
