"""Observe completed SELECTs without replacing drivers or application methods."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(frozen=True)
class Statement:
    """A completed query; parameter rendering follows the source logger/event."""

    parameters: str
    sql: str


class QueryLog(logging.Handler):
    """Consume snekql's runtime DEBUG completion records, not compiler invocations."""

    def __init__(self, statements: list[Statement]) -> None:
        super().__init__()
        self.statements: list[Statement] = statements

    def emit(self, record: logging.LogRecord) -> None:
        _, separator, executed = record.getMessage().partition(" executed: ")
        if separator and executed.startswith("SELECT "):
            sql, _, parameters = executed.rpartition(" params=")
            self.statements.append(
                Statement(sql=sql, parameters=parameters.rsplit(" rows=", 1)[0])
            )


@contextmanager
def capture(statements: list[Statement], engine: AsyncEngine) -> Iterator[None]:
    """Restore process logging policy after a sequential research observation."""

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def completed(
        _connection: Any,
        _cursor: Any,
        statement: str,
        parameters: Any,
        _context: Any,
        _executemany: bool,  # noqa: FBT001 - SQLAlchemy event signature.
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT "):
            statements.append(Statement(sql=statement, parameters=repr(parameters)))

    logger = logging.getLogger("snekql.runtime")
    previous = logger.level
    handler = QueryLog(statements)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield
    finally:
        event.remove(engine.sync_engine, "after_cursor_execute", completed)
        logger.removeHandler(handler)
        logger.setLevel(previous)
        handler.close()
