"""MariaDB runtime contract with explicit, immutable migration SQL."""

from typing import Annotated

from pydantic import Field

from snekql import mariadb as db


class Order[S = db.Pending](db.Model[S, "Order[db.Fetched]"]):
    __tablename__ = "orders"
    id: db.GenCol[int] = db.Integer(
        primary_key=True, auto_increment=True, default=db.PENDING_GENERATION
    )
    price_cents: db.Col[Annotated[int, Field(strict=True, ge=0, le=9999999999)]] = (
        db.Integer()
    )
    quantity: db.Col[Annotated[int, Field(strict=True, ge=1, le=2147483647)]] = (
        db.Integer()
    )
    status: db.GenCol[str] = db.Text(default=db.PENDING_GENERATION)
    created_at: db.GenCol[db.UtcDatetime] = db.DateTime(default=db.CurrentTimestamp)


MIGRATIONS = {
    "001_orders": """CREATE TABLE orders (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        price_cents BIGINT NOT NULL CHECK (price_cents BETWEEN 0 AND 9999999999),
        quantity BIGINT NOT NULL CHECK (quantity BETWEEN 1 AND 2147483647),
        status VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL DEFAULT 'pending',
        created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
    ) ENGINE=InnoDB"""
}
