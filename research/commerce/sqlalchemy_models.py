"""SQLAlchemy declarations, with explicit storage matching as a separate track."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    create_mock_engine,
    func,
    text,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def models(backend: str, track: str) -> dict[str, Any]:
    """Matched SQLite annotations describe TEXT, not custom Python codecs."""
    matched = track == "matched"
    integer = BigInteger if backend == "mariadb" and matched else Integer
    money = Text if backend == "sqlite" and matched else Numeric(10, 2)
    timestamp: Any = DateTime(timezone=True)
    server_clock: Any = func.current_timestamp()
    if matched:
        timestamp = Text if backend == "sqlite" else DATETIME(fsp=3)
        server_clock = (
            text("(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))")
            if backend == "sqlite"
            else text("CURRENT_TIMESTAMP(3)")
        )
    string = Text if backend == "sqlite" and matched else String(255)

    class Base(DeclarativeBase):
        pass

    class Product(Base):
        __tablename__ = "products"
        __table_args__: Any = {  # noqa: RUF012 - SQLAlchemy instance-typed metadata.
            "sqlite_strict": matched,
            "sqlite_autoincrement": matched,
        }
        id: Mapped[int] = mapped_column(integer, primary_key=True)
        price: Mapped[Decimal | str] = mapped_column(money)

    class CentProduct(Base):
        __tablename__ = "cent_products"
        __table_args__: Any = {  # noqa: RUF012 - SQLAlchemy instance-typed metadata.
            "sqlite_strict": matched,
            "sqlite_autoincrement": matched,
        }
        id: Mapped[int] = mapped_column(integer, primary_key=True)
        price_cents: Mapped[int] = mapped_column(integer)

    class Order(Base):
        __tablename__ = "orders"
        __table_args__: Any = {  # noqa: RUF012 - SQLAlchemy instance-typed metadata.
            "sqlite_strict": matched,
            "sqlite_autoincrement": matched,
        }
        id: Mapped[int] = mapped_column(integer, primary_key=True)
        quantity: Mapped[int] = mapped_column(integer)
        status: Mapped[str] = mapped_column(string, default="pending")
        created_at: Mapped[datetime | str] = mapped_column(
            timestamp, server_default=server_clock
        )

    return {"products": Product, "cent_products": CentProduct, "orders": Order}


def ddl(backend: str, track: str) -> list[str]:
    """Capture every initial DDL statement using the selected database dialect."""
    statements: list[str] = []

    def capture(statement: Any, *_args: Any, **_kwargs: Any) -> None:
        statements.append(str(statement.compile(dialect=engine.dialect)).strip())

    engine = create_mock_engine(
        "sqlite://" if backend == "sqlite" else "mariadb+pymysql://", capture
    )
    models(backend, track)["products"].metadata.create_all(engine, checkfirst=False)
    return statements
