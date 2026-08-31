"""MariaDB benchmark Table Models."""

from __future__ import annotations

from snekql import mariadb
from snekql.mariadb import Fetched, Pending


class BenchUser[S = Pending](mariadb.Model[S, "BenchUser[Fetched]"]):
    """Narrow row used for point reads, writes, and large materialization."""

    __tablename__ = "bench_user"

    id: BenchUser.GenCol[int] = mariadb.Integer(
        primary_key=True,
        auto_increment=True,
        default=mariadb.PENDING_GENERATION,
    )
    email: BenchUser.Col[str] = mariadb.Text(nullable=False)
    payload: BenchUser.Col[str] = mariadb.Text(nullable=False)


MODELS = [BenchUser]
