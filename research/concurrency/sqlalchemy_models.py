"""SQLAlchemy counters, with optional built-in ORM version checking."""

from typing import Any

from sqlalchemy import Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def models(*, versioned: bool = False) -> type[Any]:
    """A fresh mapper can view the same table with or without version policy."""

    class Base(DeclarativeBase):
        pass

    class Counter(Base):
        __tablename__ = "counter"
        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        quantity: Mapped[int] = mapped_column(Integer)
        revision: Mapped[int] = mapped_column(Integer)
        __mapper_args__ = {"version_id_col": revision} if versioned else {}

    return Counter
