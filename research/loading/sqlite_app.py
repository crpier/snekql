"""Typed projections and explicit assembly, with parent-level pagination."""

from research.loading.sqlite_models import Customer, Line, Product, Purchase
from research.loading.views import Cursor, ItemView, OrderView, Page
from snekql.sqlite import Database, Transaction, select


class Application:
    """Own a read transaction for each application operation."""

    def __init__(self, database: Database) -> None:
        self.database: Database = database

    async def list_orders(
        self, customer_id: int, cursor: Cursor | None, limit: int
    ) -> Page:
        """Return parent-level pages independently of collection cardinality."""
        query = (
            select(Purchase.id, Purchase.placed_seq, Customer.id, Customer.name)
            .join(Customer, on=Purchase.customer_id.references(Customer.id))
            .where(Purchase.customer_id.eq(customer_id))
            .order_by(Purchase.placed_seq.desc(), Purchase.id.desc())
            .limit(limit + 1)
        )
        if cursor is not None:
            query = query.where(
                Purchase.placed_seq.lt(cursor[0])
                | (Purchase.placed_seq.eq(cursor[0]) & Purchase.id.lt(cursor[1]))
            )
        async with self.database.transaction() as transaction:
            parents = await transaction.fetch_all(query)
            selected = parents[:limit]
            orders = await self._assemble(transaction, selected)
        return Page(
            next_cursor=(selected[-1][1], selected[-1][0])
            if len(parents) > limit
            else None,
            orders=orders,
        )

    async def get_order(self, order_id: int) -> OrderView | None:
        """Return complete detached detail, or None for an absent order."""
        async with self.database.transaction() as transaction:
            parents = await transaction.fetch_all(
                select(Purchase.id, Purchase.placed_seq, Customer.id, Customer.name)
                .join(Customer, on=Purchase.customer_id.references(Customer.id))
                .where(Purchase.id.eq(order_id))
            )
            orders = await self._assemble(transaction, parents)
        return orders[0] if orders else None

    async def _assemble(
        self, transaction: Transaction, parents: list[tuple[int, int, int, str]]
    ) -> tuple[OrderView, ...]:
        """Fetch children only for selected parents; empty orders survive grouping."""
        if not parents:
            return ()
        lines = await transaction.fetch_all(
            select(
                Line.order_id,
                Line.id,
                Product.id,
                Product.name,
                Line.quantity,
                Line.unit_cents,
            )
            .join(Product, on=Line.product_id.references(Product.id))
            .where(Line.order_id.in_(*(row[0] for row in parents)))
            .order_by(Line.id.asc())
        )
        grouped: dict[int, list[ItemView]] = {row[0]: [] for row in parents}
        for order_id, line_id, product_id, name, quantity, unit_cents in lines:
            grouped[order_id].append(
                ItemView(
                    id=line_id,
                    product_id=product_id,
                    product_name=name,
                    quantity=quantity,
                    unit_cents=unit_cents,
                )
            )
        return tuple(
            OrderView(
                customer_id=row[2],
                customer_name=row[3],
                id=row[0],
                items=tuple(grouped[row[0]]),
                placed_seq=row[1],
                total_cents=sum(
                    item.quantity * item.unit_cents for item in grouped[row[0]]
                ),
            )
            for row in parents
        )
