"""Ordinary ORM relationships, with no global eager-loading defaults."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(AsyncAttrs, DeclarativeBase):
    """Metadata local to the research application."""


class Customer(Base):
    __tablename__ = "customer"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))


class Product(Base):
    __tablename__ = "product"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    current_cents: Mapped[int] = mapped_column(Integer)


class Purchase(Base):
    __tablename__ = "purchase"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer.id"))
    placed_seq: Mapped[int] = mapped_column(Integer)
    customer: Mapped[Customer] = relationship()
    items: Mapped[list[Line]] = relationship(order_by="Line.id")


class Line(Base):
    __tablename__ = "line"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("purchase.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_cents: Mapped[int] = mapped_column(Integer)
    product: Mapped[Product] = relationship()
