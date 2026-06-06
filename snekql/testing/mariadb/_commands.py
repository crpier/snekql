"""MariaDB client command construction for test-server helpers."""

from __future__ import annotations

import os
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from snekql.testing.mariadb._types import (
    MariaDBAuth,
    MariaDBTransport,
    TemporaryMariaDBServerError,
)


@dataclass(frozen=True, kw_only=True)
class MariaDBClientCommand:
    """Build executable and renderable MariaDB client commands."""

    auth: MariaDBAuth
    client: str | Path
    database: str | None
    host: str | None
    password: str
    port: int | None
    socket_path: Path | None
    transport: MariaDBTransport
    user: str

    def arguments(self, *, password_prompt: bool = False) -> tuple[str, ...]:
        """Build argv while keeping transport rules in one module."""

        arguments = [str(self.client)]
        if self.transport == "unix_socket":
            if self.socket_path is None:
                msg = "unix_socket client command requires socket_path"
                raise TemporaryMariaDBServerError(msg)
            arguments.extend(("--socket", str(self.socket_path)))
        else:
            if self.host is None or self.port is None:
                msg = "tcp client command requires host and port"
                raise TemporaryMariaDBServerError(msg)
            arguments.extend(("--protocol=tcp", "-h", self.host, "-P", str(self.port)))
        arguments.extend(("-u", self.user))
        if self.auth == "password" and password_prompt:
            arguments.append("-p")
        if self.database is not None:
            arguments.extend(("-D", self.database))
        return tuple(arguments)

    def environment(self) -> Mapping[str, str] | None:
        """Provide password credentials without exposing them in argv."""

        if self.auth != "password":
            return None
        environment = os.environ.copy()
        environment["MYSQL_PWD"] = self.password
        return environment

    def shell_command(self) -> str:
        """Render a ready-to-copy interactive client command."""

        return " ".join(
            shlex.quote(argument) for argument in self.arguments(password_prompt=True)
        )
