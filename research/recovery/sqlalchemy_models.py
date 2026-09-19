"""Ordinary ORM declarations for native update and recovery observations."""

from datetime import datetime
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from research.recovery.policy import Quantity


class ValidatedQuantity(TypeDecorator[int]):
    """Extra read policy; native Integer does not enforce the domain bound."""

    impl = Integer
    cache_ok = True

    def process_result_value(self, value: Any, dialect: Dialect) -> int:  # noqa: ARG002 - SQLAlchemy callback signature.
        return TypeAdapter[int](Quantity).validate_python(value)


def models(track: str) -> type[Any]:
    """Each run owns separate metadata and an independent identity map."""

    class Base(DeclarativeBase):
        pass

    class Entry(Base):
        __tablename__ = "entries"
        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        code: Mapped[str] = mapped_column(String(255), unique=True)
        quantity: Mapped[int] = mapped_column(
            ValidatedQuantity() if track == "validated" else Integer()
        )
        note: Mapped[str | None] = mapped_column(String(255), nullable=True)
        occurred_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True).with_variant(DATETIME(fsp=3), "mysql")
        )

    return Entry
