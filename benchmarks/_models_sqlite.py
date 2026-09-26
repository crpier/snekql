"""SQLite benchmark Table Models."""

from __future__ import annotations

from typing import ClassVar

from snekql.sqlite import (
    PENDING_GENERATION,
    Integer,
    Model,
    Pending,
    ReadType,
    Row,
    Text,
)


class BenchUser[S = Pending](Model[S]):
    """Narrow row used for point reads, writes, and large materialization."""

    __row_type__: ClassVar[ReadType[BenchUser[Row]]]

    __tablename__ = "bench_user"

    id: BenchUser.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: BenchUser.Col[str] = Text(nullable=False)
    payload: BenchUser.Col[str] = Text(nullable=False)


class BenchProfile[S = Pending](Model[S]):
    """One related payload per seeded user for indexed join comparisons."""

    __row_type__: ClassVar[ReadType[BenchProfile[Row]]]

    __tablename__ = "bench_profile"

    user_id: BenchProfile.Col[int] = Integer(primary_key=True)
    payload: BenchProfile.Col[str] = Text(nullable=False)


class BenchWrite[S = Pending](Model[S]):
    """Explicit identities make committed bulk-write results reproducible."""

    __row_type__: ClassVar[ReadType[BenchWrite[Row]]]

    __tablename__ = "bench_write"

    id: BenchWrite.Col[int] = Integer(primary_key=True)
    email: BenchWrite.Col[str] = Text(nullable=False)
    payload: BenchWrite.Col[str] = Text(nullable=False)


MODELS = [BenchUser]
