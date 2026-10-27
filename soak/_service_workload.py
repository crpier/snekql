"""Public builder workloads with a bounded, independently reconciled write ledger."""

import asyncio
from collections.abc import Sequence
from contextlib import AsyncExitStack
from random import Random
from typing import Any, ClassVar

from snekql import mariadb, sqlite


class SQLiteRecord[S = sqlite.Pending](sqlite.Model[S]):
    """Fixed read fixtures and one independently owned ledger row per worker."""

    __tablename__ = "soak_record"
    __row_type__: ClassVar[sqlite.ReadType[SQLiteRecord[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    sequence: sqlite.Col[int] = sqlite.Integer()
    payload: sqlite.Col[str] = sqlite.Text()


class MariaDBRecord[S = mariadb.Pending](mariadb.Model[S]):
    """The same logical contract on native MariaDB storage."""

    __tablename__ = "soak_record"
    __row_type__: ClassVar[mariadb.ReadType[MariaDBRecord[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    sequence: mariadb.Col[int] = mariadb.Integer()
    payload: mariadb.Col[str] = mariadb.Text(length=512)


class SoakError(Exception):
    """A workload or recovery invariant failed; never retry it into success."""


def require(condition: bool, message: str) -> None:  # noqa: FBT001
    """Keep correctness checks active even under python -O."""
    if not condition:
        raise SoakError(message)


class Workload:
    """Dynamic backend selection stays at this source-checkout adapter boundary."""

    def __init__(  # noqa: PLR0913
        self,
        database: Any,
        namespace: Any,
        *,
        rows: int,
        workers: int,
        batch_size: int,
        slow_consumer: float,
        seed: int,
    ) -> None:
        self.database = database
        self.sql = namespace
        self.model: Any = SQLiteRecord if namespace is sqlite else MariaDBRecord
        self.rows = rows
        self.batch_size = batch_size
        self.slow_consumer = slow_consumer
        self.seed = seed
        self.writes = [0] * workers
        self.cancelled_waiters = 0

    def payload(self, identity: int) -> str:
        """Fixture values are prescribed independently of database reads."""
        return f"row:{identity}:seed:{self.seed}:" * 4

    async def prepare(self) -> None:
        """Replay owned literal DDL; migrations themselves are not under test here."""
        suffix = " STRICT" if self.sql is sqlite else " ENGINE=InnoDB"
        await self.database.migrate(
            {
                "001_service_fixture": (
                    "CREATE TABLE soak_record (id BIGINT PRIMARY KEY, "
                    "sequence BIGINT NOT NULL, payload VARCHAR(512) "
                    "COLLATE utf8mb4_bin NOT NULL)"
                    " ENGINE=InnoDB"
                    if self.sql is mariadb
                    else "CREATE TABLE soak_record (id INTEGER PRIMARY KEY, "
                    "sequence INTEGER NOT NULL, payload TEXT NOT NULL)" + suffix
                ),
            }
        )
        await self.database.verify([self.model])
        async with self.database.transaction() as tx:
            for identity in range(1, self.rows + len(self.writes) + 1):
                await tx.execute(
                    self.sql.insert(
                        self.model(
                            id=identity, sequence=0, payload=self.payload(identity)
                        )
                    )
                )

    def check_record(self, record: Any, identity: int) -> None:
        """Compare every read field to a known fixture, not a database-derived sum."""
        require(
            (record.id, record.sequence, record.payload)
            == (identity, 0, self.payload(identity)),
            "read fixture mismatch",
        )

    async def read(self, random: Random) -> None:
        """Read and validate an immutable record through a builder Table Model."""
        identity = random.randint(1, self.rows)
        async with self.database.transaction() as tx:
            record = await tx.fetch_one(
                self.sql.select(self.model).where(self.model.id.eq(identity))
            )
            self.check_record(record, identity)

    async def write(self, worker: int) -> None:
        """Increment one worker-owned ledger; record success only after commit."""
        identity = self.rows + worker + 1
        sequence = self.writes[worker] + 1
        token = f"worker:{worker}:sequence:{sequence}:seed:{self.seed}"
        async with self.database.transaction() as tx:
            affected = await tx.execute(
                self.sql.update(self.model)
                .set(
                    self.model.sequence.to_expr(self.model.sequence.add(1)),
                    self.model.payload.to(token),
                )
                .where(self.model.id.eq(identity))
            )
            require(affected == 1, "write did not affect exactly one ledger row")
        require(tx.commit_outcome == "committed", "write lacks commit acknowledgement")
        self.writes[worker] = sequence

    async def stream(self, *, early: bool) -> None:
        """Check exact ordered identities, including slow and early consumers."""
        count = 0
        async with self.database.transaction() as tx:
            query = (
                self.sql.select(self.model)
                .where(self.model.id.lte(self.rows))
                .order_by(self.model.id.asc())
            )
            async with tx.fetch_chunks(query, size=self.batch_size) as batches:
                async for batch in batches:
                    require(0 < len(batch) <= self.batch_size, "unbounded stream batch")
                    for record in batch:
                        count += 1
                        self.check_record(record, count)
                    await asyncio.sleep(self.slow_consumer)
                    if early:
                        break
        require(count > 0, "stream delivered no rows")
        require(early or count == self.rows, "stream lost rows")

    async def cancel_waiter(
        self, competitors: Sequence[asyncio.Task[None]] = ()
    ) -> None:
        """Saturate admission using real leases and cancel a provably queued task."""
        async with AsyncExitStack() as owners:
            for _ in range(self.database.pool_stats().capacity):
                await owners.enter_async_context(self.database.transaction())
            before = self.database.pool_stats().acquisition_cancellations

            async def waiter() -> None:
                async with self.database.transaction():
                    message = "waiter entered a fully occupied pool"
                    raise SoakError(message)

            async with asyncio.TaskGroup() as tasks:
                task = tasks.create_task(waiter())
                # With every lease held here, each unfinished worker can own
                # at most one queued acquisition. Requiring one additional
                # waiter proves this task queued too, not merely a competitor.
                while self.database.pool_stats().waiters < 1 + sum(
                    not competitor.done() for competitor in competitors
                ):
                    if task.done():
                        await task
                    await asyncio.sleep(0)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    self.cancelled_waiters += 1
            require(
                self.database.pool_stats().acquisition_cancellations == before + 1,
                "queued cancellation was not accounted for",
            )

    async def verify(self) -> None:
        """Reconcile all acknowledged writes and all read fixtures after draining."""
        await self.stream(early=False)
        async with self.database.transaction() as tx:
            records = await tx.fetch_all(
                self.sql.select(self.model)
                .where(self.model.id.gt(self.rows))
                .order_by(self.model.id.asc())
            )
        require(len(records) == len(self.writes), "ledger row count mismatch")
        for worker, record in enumerate(records):
            sequence = self.writes[worker]
            identity = self.rows + worker + 1
            expected_payload = (
                f"worker:{worker}:sequence:{sequence}:seed:{self.seed}"
                if sequence
                else self.payload(identity)
            )
            require(
                (record.id, record.sequence, record.payload)
                == (identity, sequence, expected_payload),
                "persisted ledger differs from acknowledged writes",
            )
