"""Shared validated results for comparative database adapters."""

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from pydantic import BaseModel


class ComparisonError(Exception):
    """A comparison cannot certify its workload or configuration."""


class Record(BaseModel):
    """Every adapter validates the same complete result contract once."""

    model_config = {"strict": True, "extra": "forbid"}

    email: str
    id: int
    payload: str


type Read = Callable[[int], Awaitable[list[Record]]]


@dataclass
class StreamObservation:
    """Verify ordered records online without retaining a complete result set."""

    batches: int = 0
    identity_sum: int = 0
    max_batch_rows: int = 0
    rows: int = 0

    def consume(self, records: Iterable[Record]) -> None:
        """Reject missing, duplicate, reordered or corrupted records immediately."""
        batch_rows = 0
        for record in records:
            expected_id = self.rows + 1
            if (
                record.id != expected_id
                or record.email != f"user{expected_id}@example.com"
                or record.payload != "x" * 32
            ):
                message = "stream did not return its expected ordered record"
                raise ComparisonError(message)
            self.rows += 1
            self.identity_sum += record.id
            batch_rows += 1
        if batch_rows:
            self.batches += 1
            self.max_batch_rows = max(self.max_batch_rows, batch_rows)


type Bulk = Callable[[int, int], Awaitable[list[Record]]]
type Reset = Callable[[], Awaitable[None]]


type Stream = Callable[[int], Awaitable[StreamObservation]]


@dataclass(frozen=True, kw_only=True)
class ReadSession:
    """A transaction operation with optional observed connection policy."""

    bulk: Bulk
    reset_bulk: Reset
    join: Read
    read: Read
    stream: Stream
    policy: dict[str, object] | None = None
