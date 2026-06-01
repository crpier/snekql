"""MariaDB storage declarations for table models."""

from __future__ import annotations

from collections.abc import Callable
from types import EllipsisType
from typing import Any

from snekql.storage import AttrConfig, CurrentTimestamp, build_attr


class Integer:
    """MariaDB integer column declaration for table model fields.

    >>> class User[S = Pending](Model[S, "User[Fetched]"]):
    ...     id: User.GenCol[int] = Integer(primary_key=True, default=MISSING)
    """

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
    """MariaDB JSON column declaration for JSON-compatible model values."""

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
                storage_type_name="Json",
            ),
        )


class Boolean:
    """MariaDB boolean column declaration for bool model values."""

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

    def __new__(
        cls,
        *,
        server_default: object | None = None,
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
                server_default=server_default,
                unique=unique,
                sqlite_storage_class="TEXT",
                storage_type_name="DateTime",
            ),
        )


__all__ = [
    "Blob",
    "Boolean",
    "CurrentTimestamp",
    "DateTime",
    "Integer",
    "Json",
    "Real",
    "Text",
]
