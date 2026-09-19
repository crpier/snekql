"""ORM eager loading followed by explicit detached application values."""

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import joinedload, lazyload, raiseload, selectinload

from research.loading.sqlalchemy_models import Line, Purchase
from research.loading.views import Cursor, ItemView, OrderView, Page


class Application:
    """A new Session per operation, never an accidentally warmed identity map."""

    def __init__(self, engine: AsyncEngine, strategy: str) -> None:
        self.engine: AsyncEngine = engine
        self.strategy: str = strategy

    async def list_orders(
        self, customer_id: int, cursor: Cursor | None, limit: int
    ) -> Page:
        """Apply LIMIT to orders independently of the chosen collection loader."""
        query = (
            self._query()
            .where(Purchase.customer_id == customer_id)
            .order_by(Purchase.placed_seq.desc(), Purchase.id.desc())
            .limit(limit + 1)
        )
        if cursor is not None:
            query = query.where(
                (Purchase.placed_seq < cursor[0])
                | ((Purchase.placed_seq == cursor[0]) & (Purchase.id < cursor[1]))
            )
        async with AsyncSession(self.engine) as session, session.begin():
            parents = (await session.scalars(query)).unique().all()
            if self.strategy == "per-order":
                for order in parents[:limit]:
                    await order.awaitable_attrs.items
            orders = tuple(self._view(order) for order in parents[:limit])
        return Page(
            next_cursor=(orders[-1].placed_seq, orders[-1].id)
            if len(parents) > limit
            else None,
            orders=orders,
        )

    async def get_order(self, order_id: int) -> OrderView | None:
        """Return complete detached detail, or None for an absent order."""
        query = self._query().where(Purchase.id == order_id)
        async with AsyncSession(self.engine) as session, session.begin():
            order = (await session.scalars(query)).unique().one_or_none()
            if order is not None and self.strategy == "per-order":
                await order.awaitable_attrs.items
            return None if order is None else self._view(order)

    def _query(self) -> Select[tuple[Purchase]]:
        """Choose collection loading independently of the scalar customer join."""
        if self.strategy == "joined":
            collection = joinedload(Purchase.items)
        elif self.strategy == "per-order":
            collection = lazyload(Purchase.items)
        else:
            collection = selectinload(Purchase.items)
        return select(Purchase).options(
            joinedload(Purchase.customer),
            collection.joinedload(Line.product),
            raiseload("*"),
        )

    @staticmethod
    def _view(order: Purchase) -> OrderView:
        """Copy loaded values so the API response never needs an ORM session."""
        items = tuple(
            ItemView(
                id=line.id,
                product_id=line.product.id,
                product_name=line.product.name,
                quantity=line.quantity,
                unit_cents=line.unit_cents,
            )
            for line in order.items
        )
        return OrderView(
            customer_id=order.customer.id,
            customer_name=order.customer.name,
            id=order.id,
            items=items,
            placed_seq=order.placed_seq,
            total_cents=sum(item.quantity * item.unit_cents for item in items),
        )
