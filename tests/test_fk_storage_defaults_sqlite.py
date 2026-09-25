"""Storage declarations retain soft-FK targets across default forms."""

from typing import TYPE_CHECKING, ClassVar, assert_type

from snekql import sqlite


class Target[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Target[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)


class IntegerDefaults[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[IntegerDefaults[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True, default=1)
    null: sqlite.FKCol[Target, int | None] = sqlite.Integer(default=None)
    literal: sqlite.FKCol[Target, int] = sqlite.Integer(default=1)
    factory: sqlite.FKCol[Target, int] = sqlite.Integer(default_factory=lambda: 1)
    null_factory: sqlite.FKCol[Target, int | None] = sqlite.Integer(
        default_factory=lambda: None
    )


class RealDefaults[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[RealDefaults[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True, default=1)
    null: sqlite.FKCol[Target, float | None] = sqlite.Real(default=None)
    literal: sqlite.FKCol[Target, float] = sqlite.Real(default=1.5)
    factory: sqlite.FKCol[Target, float] = sqlite.Real(default_factory=lambda: 1.5)
    null_factory: sqlite.FKCol[Target, float | None] = sqlite.Real(
        default_factory=lambda: None
    )


class TextDefaults[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[TextDefaults[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True, default=1)
    null: sqlite.FKCol[Target, str | None] = sqlite.Text(default=None)
    literal: sqlite.FKCol[Target, str] = sqlite.Text(default="key")
    factory: sqlite.FKCol[Target, str] = sqlite.Text(default_factory=lambda: "key")
    null_factory: sqlite.FKCol[Target, str | None] = sqlite.Text(
        default_factory=lambda: None
    )


class BlobDefaults[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[BlobDefaults[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True, default=1)
    null: sqlite.FKCol[Target, bytes | None] = sqlite.Blob(default=None)
    literal: sqlite.FKCol[Target, bytes] = sqlite.Blob(default=b"key")
    factory: sqlite.FKCol[Target, bytes] = sqlite.Blob(default_factory=lambda: b"key")
    null_factory: sqlite.FKCol[Target, bytes | None] = sqlite.Blob(
        default_factory=lambda: None
    )


if TYPE_CHECKING:
    assert_type(IntegerDefaults().null, int | None)
    assert_type(IntegerDefaults().literal, int)
    assert_type(IntegerDefaults().factory, int)
    assert_type(IntegerDefaults().null_factory, int | None)
    assert_type(RealDefaults().null, float | None)
    assert_type(RealDefaults().literal, float)
    assert_type(RealDefaults().factory, float)
    assert_type(RealDefaults().null_factory, float | None)
    assert_type(TextDefaults().null, str | None)
    assert_type(TextDefaults().literal, str)
    assert_type(TextDefaults().factory, str)
    assert_type(TextDefaults().null_factory, str | None)
    assert_type(BlobDefaults().null, bytes | None)
    assert_type(BlobDefaults().literal, bytes)
    assert_type(BlobDefaults().factory, bytes)
    assert_type(BlobDefaults().null_factory, bytes | None)
