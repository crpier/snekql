"""mariadb commerce declarations using snekql's public namespace."""

from decimal import Decimal
from typing import Annotated, Any

from pydantic import Field

from snekql import mariadb as db


def models() -> dict[str, Any]:
    """Declare fresh models for scaffold and construction observations."""

    class Product[S = db.Pending](db.Model[S, "Product[db.Fetched]"]):
        __tablename__ = "products"
        id: db.GenCol[int] = db.Integer(
            primary_key=True, auto_increment=True, default=db.PENDING_GENERATION
        )
        price: db.Col[Annotated[Decimal, Field(ge=0)]] = db.Decimal(10, 2)

    class CentProduct[S = db.Pending](db.Model[S, "CentProduct[db.Fetched]"]):
        __tablename__ = "cent_products"
        id: db.GenCol[int] = db.Integer(
            primary_key=True, auto_increment=True, default=db.PENDING_GENERATION
        )
        price_cents: db.Col[Annotated[int, Field(ge=0)]] = db.Integer()

    class Order[S = db.Pending](db.Model[S, "Order[db.Fetched]"]):
        __tablename__ = "orders"
        id: db.GenCol[int] = db.Integer(
            primary_key=True, auto_increment=True, default=db.PENDING_GENERATION
        )
        quantity: db.Col[Annotated[int, Field(gt=0)]] = db.Integer()
        status: db.Col[str] = db.Text(default="pending")
        created_at: db.GenCol[db.UtcDatetime] = db.DateTime(default=db.CurrentTimestamp)

    return {"products": Product, "cent_products": CentProduct, "orders": Order}


def ddl() -> list[str]:
    """These fixed declarations contain no embedded statement separators."""
    return [
        part.strip()
        for part in db.scaffold(list(models().values())).split(";")
        if part.strip()
    ]
