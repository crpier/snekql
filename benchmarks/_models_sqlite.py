"""SQLite benchmark Table Models."""

from __future__ import annotations

from snekql.sqlite import (
    PENDING_GENERATION,
    Fetched,
    Integer,
    Model,
    Pending,
    Text,
)


class BenchUser[S = Pending](Model[S, "BenchUser[Fetched]"]):
    """Narrow row used for point reads, writes, and large materialization."""

    __tablename__ = "bench_user"

    id: BenchUser.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: BenchUser.Col[str] = Text(nullable=False)
    payload: BenchUser.Col[str] = Text(nullable=False)


MODELS = [BenchUser]
