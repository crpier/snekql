"""Structured logging helpers for behavior tests."""

from __future__ import annotations


class NullStructuredLogger:
    """Structured logger fake that intentionally ignores all events."""

    def debug(self, event: str, **fields: object) -> None:
        _ = event
        _ = fields

    def info(self, event: str, **fields: object) -> None:
        _ = event
        _ = fields

    def warning(self, event: str, **fields: object) -> None:
        _ = event
        _ = fields

    def error(self, event: str, **fields: object) -> None:
        _ = event
        _ = fields


NULL_LOGGER = NullStructuredLogger()
