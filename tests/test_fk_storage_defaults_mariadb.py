"""Storage declarations retain soft-FK targets across default forms."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, assert_type
from uuid import UUID

from snekql import mariadb


class Target[S = mariadb.Pending](mariadb.Model[S, "Target[mariadb.Fetched]"]):
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)


class IntegerDefaults[S = mariadb.Pending](
    mariadb.Model[S, "IntegerDefaults[mariadb.Fetched]"]
):
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True, default=1)
    null: mariadb.FKCol[Target, int | None] = mariadb.Integer(default=None)
    literal: mariadb.FKCol[Target, int] = mariadb.Integer(default=1)
    factory: mariadb.FKCol[Target, int] = mariadb.Integer(default_factory=lambda: 1)
    null_factory: mariadb.FKCol[Target, int | None] = mariadb.Integer(
        default_factory=lambda: None
    )


class RealDefaults[S = mariadb.Pending](
    mariadb.Model[S, "RealDefaults[mariadb.Fetched]"]
):
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True, default=1)
    null: mariadb.FKCol[Target, float | None] = mariadb.Real(default=None)
    literal: mariadb.FKCol[Target, float] = mariadb.Real(default=1.5)
    factory: mariadb.FKCol[Target, float] = mariadb.Real(default_factory=lambda: 1.5)
    null_factory: mariadb.FKCol[Target, float | None] = mariadb.Real(
        default_factory=lambda: None
    )


class TextDefaults[S = mariadb.Pending](
    mariadb.Model[S, "TextDefaults[mariadb.Fetched]"]
):
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True, default=1)
    null: mariadb.FKCol[Target, str | None] = mariadb.Text(default=None)
    literal: mariadb.FKCol[Target, str] = mariadb.Text(default="key")
    factory: mariadb.FKCol[Target, str] = mariadb.Text(default_factory=lambda: "key")
    null_factory: mariadb.FKCol[Target, str | None] = mariadb.Text(
        default_factory=lambda: None
    )


class BlobDefaults[S = mariadb.Pending](
    mariadb.Model[S, "BlobDefaults[mariadb.Fetched]"]
):
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True, default=1)
    null: mariadb.FKCol[Target, bytes | None] = mariadb.Blob(default=None)
    literal: mariadb.FKCol[Target, bytes] = mariadb.Blob(default=b"key")
    factory: mariadb.FKCol[Target, bytes] = mariadb.Blob(default_factory=lambda: b"key")
    null_factory: mariadb.FKCol[Target, bytes | None] = mariadb.Blob(
        default_factory=lambda: None
    )


class LongTextDefaults[S = mariadb.Pending](
    mariadb.Model[S, "LongTextDefaults[mariadb.Fetched]"]
):
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True, default=1)
    null: mariadb.FKCol[Target, str | None] = mariadb.LongText(default=None)
    literal: mariadb.FKCol[Target, str] = mariadb.LongText(default="key")
    factory: mariadb.FKCol[Target, str] = mariadb.LongText(
        default_factory=lambda: "key"
    )
    null_factory: mariadb.FKCol[Target, str | None] = mariadb.LongText(
        default_factory=lambda: None
    )


class BooleanDefaults[S = mariadb.Pending](
    mariadb.Model[S, "BooleanDefaults[mariadb.Fetched]"]
):
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True, default=1)
    null: mariadb.FKCol[Target, bool | None] = mariadb.Boolean(default=None)
    literal: mariadb.FKCol[Target, bool] = mariadb.Boolean(default=True)
    factory: mariadb.FKCol[Target, bool] = mariadb.Boolean(default_factory=lambda: True)
    null_factory: mariadb.FKCol[Target, bool | None] = mariadb.Boolean(
        default_factory=lambda: None
    )


class DateTimeDefaults[S = mariadb.Pending](
    mariadb.Model[S, "DateTimeDefaults[mariadb.Fetched]"]
):
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True, default=1)
    null: mariadb.FKCol[Target, datetime | None] = mariadb.DateTime(default=None)
    literal: mariadb.FKCol[Target, datetime] = mariadb.DateTime(
        default=datetime(2026, 1, 1, tzinfo=UTC)
    )
    factory: mariadb.FKCol[Target, datetime] = mariadb.DateTime(
        default_factory=lambda: datetime(2026, 1, 1, tzinfo=UTC)
    )
    null_factory: mariadb.FKCol[Target, datetime | None] = mariadb.DateTime(
        default_factory=lambda: None
    )


class UuidDefaults[S = mariadb.Pending](
    mariadb.Model[S, "UuidDefaults[mariadb.Fetched]"]
):
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True, default=1)
    null: mariadb.FKCol[Target, UUID | None] = mariadb.Uuid(default=None)
    literal: mariadb.FKCol[Target, UUID] = mariadb.Uuid(default=UUID(int=1))
    factory: mariadb.FKCol[Target, UUID] = mariadb.Uuid(
        default_factory=lambda: UUID(int=1)
    )
    null_factory: mariadb.FKCol[Target, UUID | None] = mariadb.Uuid(
        default_factory=lambda: None
    )


class DecimalDefaults[S = mariadb.Pending](
    mariadb.Model[S, "DecimalDefaults[mariadb.Fetched]"]
):
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True, default=1)
    null: mariadb.FKCol[Target, Decimal | None] = mariadb.Decimal(20, 2, default=None)
    literal: mariadb.FKCol[Target, Decimal] = mariadb.Decimal(
        20, 2, default=Decimal("1.25")
    )
    factory: mariadb.FKCol[Target, Decimal] = mariadb.Decimal(
        20, 2, default_factory=lambda: Decimal("1.25")
    )
    null_factory: mariadb.FKCol[Target, Decimal | None] = mariadb.Decimal(
        20, 2, default_factory=lambda: None
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
    assert_type(LongTextDefaults().null, str | None)
    assert_type(LongTextDefaults().literal, str)
    assert_type(LongTextDefaults().factory, str)
    assert_type(LongTextDefaults().null_factory, str | None)
    assert_type(BooleanDefaults().null, bool | None)
    assert_type(BooleanDefaults().literal, bool)
    assert_type(BooleanDefaults().factory, bool)
    assert_type(BooleanDefaults().null_factory, bool | None)
    assert_type(DateTimeDefaults().null, datetime | None)
    assert_type(DateTimeDefaults().literal, datetime)
    assert_type(DateTimeDefaults().factory, datetime)
    assert_type(DateTimeDefaults().null_factory, datetime | None)
    assert_type(UuidDefaults().null, UUID | None)
    assert_type(UuidDefaults().literal, UUID)
    assert_type(UuidDefaults().factory, UUID)
    assert_type(UuidDefaults().null_factory, UUID | None)
    assert_type(DecimalDefaults().null, Decimal | None)
    assert_type(DecimalDefaults().literal, Decimal)
    assert_type(DecimalDefaults().factory, Decimal)
    assert_type(DecimalDefaults().null_factory, Decimal | None)
