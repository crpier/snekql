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


class BenchProfile[S = Pending](Model[S, "BenchProfile[Fetched]"]):
    """One related payload per seeded user for indexed join comparisons."""

    __tablename__ = "bench_profile"

    user_id: BenchProfile.Col[int] = Integer(primary_key=True)
    payload: BenchProfile.Col[str] = Text(nullable=False)


class BenchWrite[S = Pending](Model[S, "BenchWrite[Fetched]"]):
    """Explicit identities make committed bulk-write results reproducible."""

    __tablename__ = "bench_write"

    id: BenchWrite.Col[int] = Integer(primary_key=True)
    email: BenchWrite.Col[str] = Text(nullable=False)
    payload: BenchWrite.Col[str] = Text(nullable=False)


MODELS = [BenchUser]
