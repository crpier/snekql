"""Public index declarations and normalized model index metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar, cast

from snekql.errors import ModelDeclarationError
from snekql.expressions import Predicate
from snekql.storage import (
    Attr,
    StorageBackend,
    _annotation_core_types,
    _extract_logical_type,
    _json_payload_annotation,
    _resolve_model_hint,
)

if TYPE_CHECKING:
    from snekql._checks import CheckExpression

OwnerT = TypeVar("OwnerT")


@dataclass(frozen=True)
class Index[OwnerT]:
    """Public table-level index declaration.

    MariaDB accepts `prefix_lengths`, with one positive character count or None
    per member. None indexes the full column. Explicit prefixes require ordinary
    string Text/LongText storage; LongText requires a prefix. Server key limits
    still apply. SQLite rejects this option.

    SQLite accepts `where=` with the bounded CHECK predicate grammar. Return
    indexes from a synchronous `__indexes__` classmethod when using bound-column
    predicates. Annotate its result as `list[sqlite.Index[Self]]`; the factory
    runs once after column metadata is frozen. False and NULL exclude rows.
    MariaDB rejects partial predicates.

    >>> from snekql import mariadb
    >>> class Document[S = mariadb.Pending](mariadb.Model[S, "Document[mariadb.Fetched]"]):
    ...     body: mariadb.Col[str] = mariadb.LongText()
    ...     __indexes__ = [mariadb.Index(body, prefix_lengths=(128,))]
    """

    columns: tuple[Attr[Any, Any, OwnerT, Any, Any], ...]
    unique: bool
    name: str | None
    prefix_lengths: tuple[int | None, ...] | None
    where: Predicate[OwnerT] | None

    def __init__(  # noqa: C901
        self,
        *columns: Attr[Any, Any, OwnerT, Any, Any],
        unique: bool = False,
        name: str | None = None,
        prefix_lengths: tuple[int | None, ...] | None = None,
        where: Predicate[OwnerT] | None = None,
    ) -> None:
        if not columns:
            msg = "Index() requires at least one column"
            raise ModelDeclarationError(msg)
        if isinstance(prefix_lengths, tuple):
            prefix_lengths = tuple(prefix_lengths)
        if prefix_lengths is not None and (
            not isinstance(prefix_lengths, tuple) or len(prefix_lengths) != len(columns)
        ):
            msg = "prefix_lengths must be a tuple with one entry per index column"
            raise ModelDeclarationError(msg)
        prefixes = (
            prefix_lengths if prefix_lengths is not None else (None,) * len(columns)
        )
        seen_column_ids: set[int] = set()
        for column, prefix in zip(columns, prefixes, strict=True):
            if not isinstance(column, Attr):
                msg = "Index() arguments must be snekql column descriptors"
                raise ModelDeclarationError(msg)
            if prefix is not None:
                if type(prefix) is not int or prefix <= 0:
                    msg = "index prefix lengths must be positive integers or None"
                    raise ModelDeclarationError(msg)
                if column.storage_type_name not in ("Text", "LongText"):
                    msg = "index prefixes require ordinary text storage"
                    raise ModelDeclarationError(msg)
                # LONGTEXT has at most 2**32 - 1 bytes, hence no more characters.
                capacity = (
                    (2**32 - 1)
                    if column.storage_type_name == "LongText"
                    else column.text_length
                )
                if capacity is not None and prefix > capacity:
                    msg = "index prefix length exceeds the column character capacity"
                    raise ModelDeclarationError(msg)
            if not column.keyable and not (
                column.storage_type_name == "LongText" and prefix is not None
            ):
                msg = "column storage does not support index declarations"
                raise ModelDeclarationError(msg)
            column_id = id(column)
            if column_id in seen_column_ids:
                msg = "Index() cannot repeat a column"
                raise ModelDeclarationError(msg)
            seen_column_ids.add(column_id)
        object.__setattr__(
            self,
            "columns",
            cast("tuple[Attr[Any, Any, OwnerT, Any, Any], ...]", columns),
        )
        object.__setattr__(self, "unique", unique)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "prefix_lengths", prefix_lengths)
        object.__setattr__(self, "where", where)


@dataclass(frozen=True, kw_only=True)
class NormalizedIndex:
    """Immutable model-owned index metadata used by schema startup."""

    column_names: tuple[str, ...]
    name: str
    unique: bool
    prefix_lengths: tuple[int | None, ...] | None = None
    where: CheckExpression | None = None


def require_index_declaration(value: object, *, backend: StorageBackend) -> Index[Any]:
    """Validate a public __indexes__ entry before normalization."""

    if not isinstance(value, Index):
        msg = "__indexes__ entries must be Index declarations"
        raise ModelDeclarationError(msg)
    if value.where is not None and backend != "sqlite":
        msg = "partial-index predicates require SQLite"
        raise ModelDeclarationError(msg)
    if value.prefix_lengths is not None:
        if backend != "mariadb":
            msg = "index prefix declarations require MariaDB"
            raise ModelDeclarationError(msg)
        for column, prefix in zip(value.columns, value.prefix_lengths, strict=True):
            if prefix is None:
                continue
            if column.owner is None or column.name is None:
                msg = "index prefix columns must be bound to a model"
                raise ModelDeclarationError(msg)
            annotation = _extract_logical_type(
                _resolve_model_hint(column.owner, column.name), column.name
            )
            if _json_payload_annotation(annotation)[0] or _annotation_core_types(
                annotation
            ) != [str]:
                msg = "index prefixes require ordinary string logical types"
                raise ModelDeclarationError(msg)
    return cast("Index[Any]", value)
