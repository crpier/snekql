"""Original MariaDB declarations for backend-owned expression controls."""

from decimal import Decimal

from snekql import mariadb


class Product[State = mariadb.Pending](
    mariadb.Model[State, "Product[mariadb.Fetched]"]
):
    product_id: mariadb.GenCol[int] = mariadb.Integer(
        primary_key=True, auto_increment=True, default=mariadb.PENDING_GENERATION
    )
    payload: mariadb.JsonCol[dict[str, int]] = mariadb.Json()
    price: mariadb.Col[Decimal] = mariadb.Decimal(12, 2)
