"""Explicit ORM policies, independent of snekql codecs."""

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import AfterValidator, AwareDatetime, Field, TypeAdapter
from sqlalchemy import BigInteger, CheckConstraint, Integer, String, Text, text
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, validates
from sqlalchemy.types import TypeDecorator, TypeEngine


def _utc_millis(instant: datetime) -> datetime:
    instant = instant.astimezone(UTC)
    return instant.replace(microsecond=instant.microsecond // 1000 * 1000)


class BoundedInteger(TypeDecorator[int]):
    """Validate bound writes too, including those that skip ORM attribute events."""

    impl = Integer
    cache_ok = True

    def __init__(self, minimum: int, maximum: int) -> None:
        super().__init__()
        self.minimum: int = minimum
        self.maximum: int = maximum
        self.adapter: TypeAdapter[int] = TypeAdapter(
            Annotated[int, Field(strict=True, ge=minimum, le=maximum)]
        )

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        return dialect.type_descriptor(
            Integer() if dialect.name == "sqlite" else BigInteger()
        )

    def process_bind_param(self, value: int | None, dialect: Dialect) -> int:  # noqa: ARG002 - SQLAlchemy callback signature.
        return self.adapter.validate_python(value)

    def process_result_value(self, value: int | None, dialect: Dialect) -> int:  # noqa: ARG002 - SQLAlchemy callback signature.
        return self.adapter.validate_python(value)


class UtcMillis(TypeDecorator[datetime]):
    """Use UTC TEXT on SQLite and naive UTC DATETIME(3) at the MariaDB boundary."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        return dialect.type_descriptor(
            Text() if dialect.name == "sqlite" else DATETIME(fsp=3)
        )

    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> str | datetime:
        instant = TypeAdapter[datetime](
            Annotated[AwareDatetime, Field(strict=True), AfterValidator(_utc_millis)]
        ).validate_python(value)
        if dialect.name == "sqlite":
            return instant.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        # MariaDB DATETIME requires naive wire values; application values stay aware.
        return instant.replace(tzinfo=None)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime:
        instant = (
            datetime.fromisoformat(value)
            if dialect.name == "sqlite"
            else value.replace(tzinfo=UTC)
        )
        return _utc_millis(instant)


def models(backend: str) -> type[Any]:
    """Return a fresh mapped class for an isolated database."""

    cents = BoundedInteger(0, 9999999999)
    quantity_type = BoundedInteger(1, 2147483647)

    class Base(DeclarativeBase):
        pass

    class Order(Base):
        __tablename__ = "orders"
        __table_args__ = (
            CheckConstraint(
                "price_cents BETWEEN 0 AND 9999999999", name="ck_price_cents"
            ),
            CheckConstraint("quantity BETWEEN 1 AND 2147483647", name="ck_quantity"),
            {"sqlite_strict": True, "sqlite_autoincrement": True},
        )
        id: Mapped[int] = mapped_column(
            Integer if backend == "sqlite" else BigInteger, primary_key=True
        )
        price_cents: Mapped[int] = mapped_column(cents)
        quantity: Mapped[int] = mapped_column(quantity_type)
        status: Mapped[str] = mapped_column(
            (
                Text() if backend == "sqlite" else String(255, collation="utf8mb4_bin")
            ).evaluates_none(),
            server_default=text("'pending'"),
        )
        created_at: Mapped[datetime] = mapped_column(
            UtcMillis().evaluates_none(),
            server_default=text(
                "(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
                if backend == "sqlite"
                else "CURRENT_TIMESTAMP(3)"
            ),
        )

        @validates("price_cents", "quantity", "created_at", "status")
        def validate_attribute(self, key: str, supplied: Any) -> Any:
            if key in ("price_cents", "quantity"):
                return (
                    cents if key == "price_cents" else quantity_type
                ).adapter.validate_python(supplied)
            if key == "created_at":
                return TypeAdapter[datetime](
                    Annotated[
                        AwareDatetime, Field(strict=True), AfterValidator(_utc_millis)
                    ]
                ).validate_python(supplied)
            return TypeAdapter[str](Annotated[str, Field(strict=True)]).validate_python(
                supplied
            )

    return Order
