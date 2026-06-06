"""Shared Temporary MariaDB Test Server types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from snekql.errors import SnekqlError

type MariaDBAuth = Literal["insecure", "password"]
type MariaDBTransport = Literal["unix_socket", "tcp"]


@dataclass(frozen=True, kw_only=True)
class MariaDBCommandResult:
    """Captured result from a MariaDB command-line client invocation."""

    returncode: int
    stderr: str
    stdout: str


class TemporaryMariaDBServerError(SnekqlError):
    """Failure while managing a local Temporary MariaDB Test Server."""
