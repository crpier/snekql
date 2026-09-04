"""MariaDB storage declarations for table models."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import EllipsisType
from typing import TYPE_CHECKING, Any, cast, overload

from snekql._query_state import require_column_model
from snekql.errors import ModelDeclarationError, ModelValidationError
from snekql.expressions import Comparable
from snekql.storage import (
    Attr,
    CurrentTimestamp,
    FKAttr,
    ForeignKey,
    PendingGeneration,
    _UnboundOwner,
)

if TYPE_CHECKING:
    from snekql._dialect_expr import CompileCtx


_DECIMAL_MAX_PRECISION = 65
_DECIMAL_MAX_SCALE = 30


@dataclass(frozen=True)
class _JsonExtractInt[OwnerT](Comparable[OwnerT, int, "int | None"]):
    """``JSON_EXTRACT(col, path)`` typed as ``int | None`` (ADR 0004 open-AST seam).

    The first dialect-specific operator: it lives entirely in the MariaDB
    namespace and reaches the core only through the structural protocols.

    * ``Comparable[OwnerT, int, int | None]`` gives it the comparison surface
      (``.gt(18)``) typed to ``int``, so it works as a ``WHERE`` operand.
    * ``__owner_model__`` / ``__compile_sql__`` satisfy ``SqlCompilable`` (the
      operand-render seam).
    * ``__compile_select_sql__`` / ``__decode__`` additionally satisfy
      ``DialectSelectable[OwnerT, int | None]`` (the projection seam), so it can
      be
      projected and Materialized without the core naming this class.

    The result is optional because ``JSON_EXTRACT`` returns SQL ``NULL`` whenever
    the path is absent -- the common case for a sparse document. A value that is
    present but not an integer is a declaration mismatch and raises rather than
    silently coercing.
    """

    column: Attr[Any, Any, Any, Any, Any]
    path: str

    def __column_owner_type__(self) -> OwnerT:
        """Typing-only witness for singleton-select owner inference."""

        raise NotImplementedError

    def __column_value_type__(self) -> int | None:
        """Typing-only witness for singleton-select result inference."""

        raise NotImplementedError

    def __owner_model__(self) -> type[OwnerT]:
        return cast("type[OwnerT]", require_column_model(self.column))

    def __compile_sql__(self, ctx: CompileCtx) -> tuple[str, tuple[object, ...]]:
        sql = f"JSON_EXTRACT({ctx.render_column(self.column)}, {ctx.placeholder})"
        return sql, (self.path,)

    def __compile_select_sql__(self, ctx: CompileCtx) -> tuple[str, tuple[object, ...]]:
        return self.__compile_sql__(ctx)

    def __decode__(self, raw: object) -> int | None:
        # A missing JSON path reaches the driver as SQL NULL -> None; the type is
        # optional precisely so this normal sparse-document case is not a crash.
        if raw is None:
            return None
        # MariaDB returns JSON scalars as text (or bytes from the driver); the
        # leaf owns this raw->typed conversion.
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode()
        try:
            return int(cast("str | int | float", raw))
        except (TypeError, ValueError) as error:
            msg = (
                f"json_extract_int({self.path!r}) expected an integer at the path "
                f"but found {raw!r}"
            )
            raise ModelValidationError(msg) from error


class JsonAttr[
    WriteOwnerT,
    LoadedOwnerT,
    OwnerT,
    WriteT,
    ReadValueT,
    SetValueT = WriteT,
    CompareT = Any,
](
    FKAttr[
        WriteOwnerT,
        LoadedOwnerT,
        OwnerT,
        WriteT,
        ReadValueT,
        Any,
        SetValueT,
        CompareT,
    ],
):
    """MariaDB JSON column descriptor carrying the JSON path operators.

    A field declared ``profile: JsonCol[...]`` resolves to this subtype, so
    ``json_extract_int`` is visible on JSON columns and nowhere else. Attaching
    the operator to the column subtype -- rather than the core ``Attr`` -- is the
    type-safety lever (ADR 0003 per-namespace columns + ADR 0004 open AST): the
    operator scopes to exactly the columns that support it.
    """

    @overload
    def __get__[AccessOwner, NonNullT](
        self: JsonAttr[
            WriteOwnerT,
            LoadedOwnerT,
            OwnerT,
            WriteT,
            NonNullT | None,
            SetValueT,
            Any,
        ],
        instance: None,
        owner: type[AccessOwner],
    ) -> JsonAttr[
        WriteOwnerT,
        LoadedOwnerT,
        AccessOwner,
        WriteT,
        NonNullT | None,
        SetValueT,
        NonNullT,
    ]: ...

    @overload
    def __get__[AccessOwner](
        self: JsonAttr[
            WriteOwnerT,
            LoadedOwnerT,
            OwnerT,
            WriteT,
            ReadValueT,
            SetValueT,
            Any,
        ],
        instance: None,
        owner: type[AccessOwner],
    ) -> JsonAttr[
        WriteOwnerT,
        LoadedOwnerT,
        AccessOwner,
        WriteT,
        ReadValueT,
        SetValueT,
        ReadValueT,
    ]: ...

    @overload
    def __get__(self, instance: WriteOwnerT, owner: type[Any]) -> WriteT: ...

    @overload
    def __get__(self, instance: LoadedOwnerT, owner: type[Any]) -> ReadValueT: ...

    def __get__(  # ty: ignore[invalid-method-override]
        self,
        instance: object | None,
        owner: type[Any],
    ) -> object:
        return cast("object", super().__get__(cast("Any", instance), owner))

    def json_extract_int(self, path: str) -> _JsonExtractInt[OwnerT]:
        """Extract an integer at ``path`` from this JSON column.

        Returns a dialect expression usable as a ``WHERE`` operand
        (``profile.json_extract_int("$.age").gt(18)``) and as a typed ``int``
        ``SELECT`` projection.
        """

        return _JsonExtractInt(column=self, path=path)


@overload
def Integer[T](
    *,
    primary_key: bool = False,
    auto_increment: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: PendingGeneration,
) -> Attr[Any, Any, _UnboundOwner, T | PendingGeneration, T]: ...


@overload
def Integer[T](
    *,
    primary_key: bool = False,
    auto_increment: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: type[CurrentTimestamp],
) -> Attr[Any, Any, _UnboundOwner, T | PendingGeneration, T]: ...


@overload
def Integer[T](
    *,
    primary_key: bool = False,
    auto_increment: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: None,
) -> Attr[Any, Any, _UnboundOwner, T | None, T | None]: ...


@overload
def Integer[T](
    *,
    primary_key: bool = False,
    auto_increment: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: T,
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


@overload
def Integer[T](
    *,
    primary_key: bool = False,
    auto_increment: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default_factory: Callable[[], T],
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


@overload
def Integer[T](
    *,
    primary_key: bool = False,
    auto_increment: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


def Integer(  # noqa: N802, PLR0913
    *,
    primary_key: bool = False,
    auto_increment: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: object = ...,
    default_factory: Callable[[], object] | EllipsisType = ...,
) -> Any:
    """MariaDB integer column declaration for table model fields.

    >>> class User[S = Pending](Model[S, "User[Fetched]"]):
    ...     id: GenCol[int] = Integer(primary_key=True, default=PENDING_GENERATION)
    """
    return FKAttr[Any, Any, Any, Any, Any, Any](
        auto_increment=auto_increment,
        default=default,
        default_factory=default_factory,
        nullable=nullable,
        primary_key=primary_key,
        index=index,
        unique=unique,
        storage_class="INTEGER",
        storage_type_name="Integer",
    )


@overload
def Real[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: PendingGeneration,
) -> Attr[Any, Any, _UnboundOwner, T | PendingGeneration, T]: ...


@overload
def Real[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: type[CurrentTimestamp],
) -> Attr[Any, Any, _UnboundOwner, T | PendingGeneration, T]: ...


@overload
def Real[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: None,
) -> Attr[Any, Any, _UnboundOwner, T | None, T | None]: ...


@overload
def Real[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: T,
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


@overload
def Real[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default_factory: Callable[[], T],
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


@overload
def Real[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


def Real(  # noqa: N802, PLR0913
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: object = ...,
    default_factory: Callable[[], object] | EllipsisType = ...,
) -> Any:
    """MariaDB real-number column declaration for float-like model values."""
    return FKAttr[Any, Any, Any, Any, Any, Any](
        default=default,
        default_factory=default_factory,
        nullable=nullable,
        primary_key=primary_key,
        index=index,
        unique=unique,
        storage_class="REAL",
        storage_type_name="Real",
    )


@overload
def Text[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: PendingGeneration,
) -> Attr[Any, Any, _UnboundOwner, T | PendingGeneration, T]: ...


@overload
def Text[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: type[CurrentTimestamp],
) -> Attr[Any, Any, _UnboundOwner, T | PendingGeneration, T]: ...


@overload
def Text[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: None,
) -> Attr[Any, Any, _UnboundOwner, T | None, T | None]: ...


@overload
def Text[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: T,
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


@overload
def Text[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default_factory: Callable[[], T],
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


@overload
def Text[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


def Text(  # noqa: N802, PLR0913
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: object = ...,
    default_factory: Callable[[], object] | EllipsisType = ...,
) -> Any:
    """MariaDB text column declaration for string model values."""
    return FKAttr[Any, Any, Any, Any, Any, Any](
        default=default,
        default_factory=default_factory,
        nullable=nullable,
        primary_key=primary_key,
        index=index,
        unique=unique,
        storage_class="TEXT",
        storage_type_name="Text",
    )


@overload
def Blob[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: PendingGeneration,
) -> Attr[Any, Any, _UnboundOwner, T | PendingGeneration, T]: ...


@overload
def Blob[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: type[CurrentTimestamp],
) -> Attr[Any, Any, _UnboundOwner, T | PendingGeneration, T]: ...


@overload
def Blob[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: None,
) -> Attr[Any, Any, _UnboundOwner, T | None, T | None]: ...


@overload
def Blob[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: T,
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


@overload
def Blob[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default_factory: Callable[[], T],
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


@overload
def Blob[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


def Blob(  # noqa: N802, PLR0913
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: object = ...,
    default_factory: Callable[[], object] | EllipsisType = ...,
) -> Any:
    """MariaDB blob column declaration for bytes model values."""
    return FKAttr[Any, Any, Any, Any, Any, Any](
        default=default,
        default_factory=default_factory,
        nullable=nullable,
        primary_key=primary_key,
        index=index,
        unique=unique,
        storage_class="BLOB",
        storage_type_name="Blob",
    )


@overload
def Decimal[T](
    precision: int,
    scale: int,
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: PendingGeneration,
) -> Attr[Any, Any, _UnboundOwner, T | PendingGeneration, T]: ...


@overload
def Decimal[T](
    precision: int,
    scale: int,
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: None,
) -> Attr[Any, Any, _UnboundOwner, T | None, T | None]: ...


@overload
def Decimal[T](
    precision: int,
    scale: int,
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: T,
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


@overload
def Decimal[T](
    precision: int,
    scale: int,
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default_factory: Callable[[], T],
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


@overload
def Decimal[T](
    precision: int,
    scale: int,
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


def Decimal(  # noqa: N802, PLR0913
    precision: int,
    scale: int,
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: object = ...,
    default_factory: Callable[[], object] | EllipsisType = ...,
) -> Any:
    """MariaDB native fixed-point decimal column declaration.

    The logical type is the field annotation, usually ``decimal.Decimal``; the
    constructor declares the native ``DECIMAL(precision, scale)`` storage shape.
    """
    if not (
        1 <= precision <= _DECIMAL_MAX_PRECISION
        and 0 <= scale <= min(_DECIMAL_MAX_SCALE, precision)
    ):
        msg = (
            "Decimal precision/scale must satisfy 1 <= precision <= 65 and "
            "0 <= scale <= min(30, precision)"
        )
        raise ModelDeclarationError(msg)
    return FKAttr[Any, Any, Any, Any, Any, Any](
        decimal_precision=precision,
        decimal_scale=scale,
        default=default,
        default_factory=default_factory,
        nullable=nullable,
        primary_key=primary_key,
        index=index,
        unique=unique,
        storage_class="TEXT",
        storage_type_name="Decimal",
    )


@overload
def Json[T](
    *,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: None,
) -> JsonAttr[Any, Any, _UnboundOwner, T | None, T | None, T | None]: ...


@overload
def Json[T](
    *,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: T,
) -> JsonAttr[Any, Any, _UnboundOwner, T, T]: ...


@overload
def Json[T](
    *,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default_factory: Callable[[], T],
) -> JsonAttr[Any, Any, _UnboundOwner, T, T]: ...


@overload
def Json[T](
    *,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
) -> JsonAttr[Any, Any, _UnboundOwner, T, T]: ...


def Json(  # noqa: N802
    *,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: object = ...,
    default_factory: Callable[[], object] | EllipsisType = ...,
) -> Any:
    """MariaDB JSON column declaration for JSON-compatible model values.

    Builds a :class:`JsonAttr` so the runtime descriptor carries the JSON path
    operators; a field annotated ``JsonCol[...]`` makes them visible to the
    type checker on JSON columns only.
    """
    return JsonAttr[Any, Any, Any, Any, Any](
        default=default,
        default_factory=default_factory,
        nullable=nullable,
        index=index,
        unique=unique,
        storage_class="TEXT",
        storage_type_name="Json",
    )


@overload
def Boolean[T](
    *,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: PendingGeneration,
) -> Attr[Any, Any, _UnboundOwner, T | PendingGeneration, T]: ...


@overload
def Boolean[T](
    *,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: type[CurrentTimestamp],
) -> Attr[Any, Any, _UnboundOwner, T | PendingGeneration, T]: ...


@overload
def Boolean[T](
    *,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: None,
) -> Attr[Any, Any, _UnboundOwner, T | None, T | None]: ...


@overload
def Boolean[T](
    *,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: T,
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


@overload
def Boolean[T](
    *,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default_factory: Callable[[], T],
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


@overload
def Boolean[T](
    *,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


def Boolean(  # noqa: N802
    *,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: object = ...,
    default_factory: Callable[[], object] | EllipsisType = ...,
) -> Any:
    """MariaDB boolean column declaration for bool model values."""
    return FKAttr[Any, Any, Any, Any, Any, Any](
        default=default,
        default_factory=default_factory,
        nullable=nullable,
        index=index,
        unique=unique,
        storage_class="INTEGER",
        storage_type_name="Boolean",
    )


@overload
def DateTime[T](
    *,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: PendingGeneration,
) -> Attr[Any, Any, _UnboundOwner, T | PendingGeneration, T]: ...


@overload
def DateTime[T](
    *,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: type[CurrentTimestamp],
) -> Attr[Any, Any, _UnboundOwner, T | PendingGeneration, T]: ...


@overload
def DateTime[T](
    *,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: None,
) -> Attr[Any, Any, _UnboundOwner, T | None, T | None]: ...


@overload
def DateTime[T](
    *,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: T,
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


@overload
def DateTime[T](
    *,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default_factory: Callable[[], T],
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


@overload
def DateTime[T](
    *,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


def DateTime(  # noqa: N802
    *,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: object = ...,
    default_factory: Callable[[], object] | EllipsisType = ...,
) -> Any:
    """MariaDB datetime column declaration for timezone-aware datetimes."""
    return FKAttr[Any, Any, Any, Any, Any, Any](
        default=default,
        default_factory=default_factory,
        nullable=nullable,
        index=index,
        unique=unique,
        storage_class="TEXT",
        storage_type_name="DateTime",
    )


@overload
def Uuid[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: PendingGeneration,
) -> Attr[Any, Any, _UnboundOwner, T | PendingGeneration, T]: ...


@overload
def Uuid[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: type[CurrentTimestamp],
) -> Attr[Any, Any, _UnboundOwner, T | PendingGeneration, T]: ...


@overload
def Uuid[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: None,
) -> Attr[Any, Any, _UnboundOwner, T | None, T | None]: ...


@overload
def Uuid[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: T,
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


@overload
def Uuid[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default_factory: Callable[[], T],
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


@overload
def Uuid[T](
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
) -> Attr[Any, Any, _UnboundOwner, T, T]: ...


def Uuid(  # noqa: N802, PLR0913
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    default: object = ...,
    default_factory: Callable[[], object] | EllipsisType = ...,
) -> Any:
    """MariaDB native ``UUID`` column declaration for ``uuid.UUID`` values.

    The native storage primitive for UUIDs (MariaDB 10.7+); the logical type is
    the field annotation (``Col[uuid.UUID]``). The driver exchanges UUID values
    as their string form, so encoding/decoding runs through the shared pydantic
    scalar codec -- no dedicated native codec. To store a UUID as raw bytes
    instead, use ``Blob()`` with a ``Col[uuid.UUID]`` annotation.

    >>> class User[S = Pending](Model[S, "User[Fetched]"]):
    ...     id: Col[uuid.UUID] = Uuid(primary_key=True, default_factory=uuid4)
    """
    return FKAttr[Any, Any, Any, Any, Any, Any](
        default=default,
        default_factory=default_factory,
        nullable=nullable,
        primary_key=primary_key,
        index=index,
        unique=unique,
        storage_class="TEXT",
        storage_type_name="Uuid",
    )


__all__ = [
    "Blob",
    "Boolean",
    "CurrentTimestamp",
    "DateTime",
    "Decimal",
    "ForeignKey",
    "Integer",
    "Json",
    "JsonAttr",
    "Real",
    "Text",
    "Uuid",
]
