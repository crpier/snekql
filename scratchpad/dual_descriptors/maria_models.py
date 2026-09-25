"""MariaDB inputs and complete values for direct column tests."""

from decimal import Decimal

from scratchpad.dual_descriptors import mariadb


class Product(mariadb.Model):
    __row__ = mariadb.paired(lambda: ProductRow)
    identity: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    price: mariadb.Col[Decimal] = mariadb.Decimal(12, 2)
    data: mariadb.JsonCol[dict[str, int]] = mariadb.Json()


class ProductRow(Product, mariadb.Row):
    table_name = "products"
