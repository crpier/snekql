"""Structured logging contracts for snekql runtime observability."""

from __future__ import annotations

import contextlib
from typing import Protocol


class StructuredLogger(Protocol):
    """Structured logger accepted by the Query Runtime.

    Any logger with structlog-style methods satisfies this protocol:

    >>> class AppLogger:
    ...     def debug(self, event: str, **fields: object) -> object:
    ...         return None
    ...     def info(self, event: str, **fields: object) -> object:
    ...         return None
    ...     def warning(self, event: str, **fields: object) -> object:
    ...         return None
    ...     def error(self, event: str, **fields: object) -> object:
    ...         return None
    >>> logger: StructuredLogger = AppLogger()
    >>> logger.debug("query executed", sql="SELECT 1", params=())
    """

    def debug(self, event: str, **fields: object) -> object: ...

    def info(self, event: str, **fields: object) -> object: ...

    def warning(self, event: str, **fields: object) -> object: ...

    def error(self, event: str, **fields: object) -> object: ...


class ResolvedStructuredLogger(Protocol):
    """Internal logger shape after snekql wraps application loggers."""

    def debug(self, event: str, **fields: object) -> None: ...

    def info(self, event: str, **fields: object) -> None: ...

    def warning(self, event: str, **fields: object) -> None: ...

    def error(self, event: str, **fields: object) -> None: ...


class _SafeStructuredLogger:
    """Best-effort logger wrapper that keeps observability out of control flow."""

    def __init__(self, *, logger: StructuredLogger) -> None:
        self.logger: StructuredLogger = logger

    def debug(self, event: str, **fields: object) -> None:
        with contextlib.suppress(Exception):
            _ = self.logger.debug(event, **fields)

    def info(self, event: str, **fields: object) -> None:
        with contextlib.suppress(Exception):
            _ = self.logger.info(event, **fields)

    def warning(self, event: str, **fields: object) -> None:
        with contextlib.suppress(Exception):
            _ = self.logger.warning(event, **fields)

    def error(self, event: str, **fields: object) -> None:
        with contextlib.suppress(Exception):
            _ = self.logger.error(event, **fields)


def resolve_structured_logger(
    *,
    logger: StructuredLogger,
) -> ResolvedStructuredLogger:
    """Return a safe structured logger for runtime internals.

    snekql treats logging as best-effort observability. A user logger failure
    should not change Database, Transaction, or query execution behavior.
    """

    return _SafeStructuredLogger(logger=logger)
