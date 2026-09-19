"""Opt-in whole-transaction retry example for SQLite, not a library retry policy.

Use transactional tables only. Do not issue raw transaction control or statements
with implicit commits. Every attempt must be safe to repeat: keep network calls,
emails, and other external side effects outside the callback, or protect them
with durable idempotency keys. An outbox row can be written in the transaction.

MariaDB applications can use the same loop with their backend's Database and
Transaction annotations. Adapt the exception handler to reconcile a durable
request ID when the commit outcome is unknown. Never replay that attempt merely
because its failure category looks transient.
"""

from collections.abc import Awaitable, Callable
from random import uniform

from anyio import sleep

from snekql.sqlite import (
    Database,
    DatabaseRuntimeError,
    Transaction,
    TransactionStateError,
)

_MAX_ATTEMPTS = 3
"""Bound retry count independently of the database's per-operation deadlines."""

_BASE_DELAY_SECONDS = 0.05
"""Full-jitter exponential waits total at most 0.15 seconds for three attempts."""


async def run_with_retry[ResultT](
    database: Database, operation: Callable[[Transaction], Awaitable[ResultT]]
) -> ResultT:
    """Return only after a successful outer exit; rethrow unsafe or exhausted failures.

    The caller opts into repeating the entire callback, including its reads.
    This example deliberately retries only deadlocks and serialization conflicts.
    It does not make every lock conflict or connection failure retryable.
    """
    attempt = 0
    while True:
        attempt += 1
        transaction = database.transaction()
        try:
            async with transaction:
                result = await operation(transaction)
        except DatabaseRuntimeError as e:
            failure = e.failure
            if (
                attempt >= _MAX_ATTEMPTS
                or transaction.commit_outcome not in ("not_attempted", "rejected")
                or failure is None
                or failure.category not in ("deadlock", "serialization_conflict")
            ):
                # Unknown commits need application-specific reconciliation. An
                # acknowledged commit followed by cleanup failure must not replay.
                raise
        else:
            if transaction.commit_outcome != "committed":
                message = "operation finished without an acknowledged commit"
                raise TransactionStateError(message)
            return result
        await sleep(uniform(0, _BASE_DELAY_SECONDS * 2 ** (attempt - 1)))
