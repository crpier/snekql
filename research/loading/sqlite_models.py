"""Explicit table declarations for the related-loading application."""

from snekql.sqlite import Fetched, ForeignKey, Integer, Model, Pending, Text


class Customer[S = Pending](Model[S, "Customer[Fetched]"]):
    id: Customer.Col[int] = Integer(primary_key=True)
    name: Customer.Col[str] = Text()


class Product[S = Pending](Model[S, "Product[Fetched]"]):
    id: Product.Col[int] = Integer(primary_key=True)
    name: Product.Col[str] = Text()
    current_cents: Product.Col[int] = Integer()


class Purchase[S = Pending](Model[S, "Purchase[Fetched]"]):
    id: Purchase.Col[int] = Integer(primary_key=True)
    customer_id: Purchase.FKCol[Customer, int] = ForeignKey(Customer.id)
    placed_seq: Purchase.Col[int] = Integer()


class Line[S = Pending](Model[S, "Line[Fetched]"]):
    id: Line.Col[int] = Integer(primary_key=True)
    order_id: Line.FKCol[Purchase, int] = ForeignKey(Purchase.id)
    product_id: Line.FKCol[Product, int] = ForeignKey(Product.id)
    quantity: Line.Col[int] = Integer()
    unit_cents: Line.Col[int] = Integer()
