"""Signature-only callable target proposal using all existing overloads."""
from collections.abc import Callable
from typing import Any, Literal, overload
from snekql.storage import Attr, FKAttr, ReferentialAction, _UnboundOwner

@overload
def foreign_key[Target, T](
    references: Attr[Any, Any, Target, Any, T] | Callable[[], Attr[Any, Any, Target, Any, T]],
    *,
    primary_key: bool = False,
    nullable: Literal[True],
    unique: bool = False,
    index: bool = False,
    on_delete: ReferentialAction | None = None,
    on_update: ReferentialAction | None = None,
    default: T,
) -> FKAttr[Any, Any, _UnboundOwner, T | None, T | None, Target, T | None]: ...


@overload
def foreign_key[Target, T](
    references: Attr[Any, Any, Target, Any, T] | Callable[[], Attr[Any, Any, Target, Any, T]],
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    on_delete: ReferentialAction | None = None,
    on_update: ReferentialAction | None = None,
    default: T,
) -> FKAttr[Any, Any, _UnboundOwner, T, T, Target, T]: ...


@overload
def foreign_key[Target, T](
    references: Attr[Any, Any, Target, Any, T] | Callable[[], Attr[Any, Any, Target, Any, T]],
    *,
    primary_key: bool = False,
    nullable: Literal[True],
    unique: bool = False,
    index: bool = False,
    on_delete: ReferentialAction | None = None,
    on_update: ReferentialAction | None = None,
) -> FKAttr[Any, Any, _UnboundOwner, T | None, T | None, Target, T | None]: ...


@overload
def foreign_key[Target, T](
    references: Attr[Any, Any, Target, Any, T] | Callable[[], Attr[Any, Any, Target, Any, T]],
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    on_delete: ReferentialAction | None = None,
    on_update: ReferentialAction | None = None,
    default: None,
) -> FKAttr[Any, Any, _UnboundOwner, T | None, T | None, Target, T | None]: ...


@overload
def foreign_key[Target, T](
    references: Attr[Any, Any, Target, Any, T] | Callable[[], Attr[Any, Any, Target, Any, T]],
    *,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    index: bool = False,
    on_delete: ReferentialAction | None = None,
    on_update: ReferentialAction | None = None,
) -> FKAttr[Any, Any, _UnboundOwner, T, T, Target]: ...

