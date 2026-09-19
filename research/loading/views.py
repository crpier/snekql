"""Detached application values, independent of either persistence library."""

from dataclasses import dataclass

type Cursor = tuple[int, int]


@dataclass(frozen=True)
class ItemView:
    """One historical order line, even when another line shares its product."""

    id: int
    product_id: int
    product_name: str
    quantity: int
    unit_cents: int


@dataclass(frozen=True)
class OrderView:
    """A complete order suitable for serialization without database access."""

    customer_id: int
    customer_name: str
    id: int
    items: tuple[ItemView, ...]
    placed_seq: int
    total_cents: int


@dataclass(frozen=True)
class Page:
    """Order-level pagination; child cardinality does not define page size."""

    next_cursor: Cursor | None
    orders: tuple[OrderView, ...]


class LoadingStudyError(Exception):
    """An unsupported configuration or invalid application request."""
