"""Backend-neutral connection settings: apply once, then verify.

snekql's correctness guarantees depend on engine settings being in effect on
*every* connection (for example SQLite ``foreign_keys`` enforcement or MariaDB
strict ``sql_mode``). Some of these settings silently no-op on misconfigured
builds or unsupported targets, so each one is applied and then read back; a
setting that did not take effect fails fast rather than degrading silently.

Backends declare their required settings as :class:`ConnectionSetting` values
and run them through :func:`apply_connection_settings` at the single per-
connection seam each backend owns.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from snekql.errors import DatabaseRuntimeError


class _Unset:
    """Sentinel marking a setting that is verified through a predicate."""


_UNSET = _Unset()


class SettingsProbe(Protocol):
    """Minimal connection seam used to apply and read back settings."""

    async def execute(self, sql: str) -> None:
        """Run a statement that produces no result of interest."""
        ...

    async def fetch_value(self, sql: str) -> object:
        """Run a probe statement and return its first column's value."""
        ...


@dataclass(frozen=True, kw_only=True)
class ConnectionSetting:
    """One required engine setting plus how to apply and verify it.

    ``apply_statements`` are executed in order (empty for verify-only settings
    such as a build-time encoding check), then ``probe_sql`` is read back and
    compared against ``expected_value`` or ``predicate``.
    """

    name: str
    probe_sql: str
    apply_statements: tuple[str, ...] = ()
    expected_value: object = _UNSET
    predicate: Callable[[object], bool] | None = None
    expectation: str = ""

    def matches(self, value: object) -> bool:
        """Whether the read-back value satisfies this setting."""

        if self.predicate is not None:
            return self.predicate(value)
        return value == self.expected_value

    def describe_expectation(self) -> str:
        """Human-readable description of the required value."""

        if self.expectation:
            return self.expectation
        if not isinstance(self.expected_value, _Unset):
            return repr(self.expected_value)
        return "a satisfied predicate"


async def apply_connection_settings(
    probe: SettingsProbe,
    settings: Sequence[ConnectionSetting],
    *,
    backend: str,
) -> None:
    """Apply each required setting and verify it actually took effect."""

    for setting in settings:
        for statement in setting.apply_statements:
            await probe.execute(statement)
        value = await probe.fetch_value(setting.probe_sql)
        if not setting.matches(value):
            msg = (
                f"{backend} connection setting {setting.name!r} did not take "
                f"effect: expected {setting.describe_expectation()}, got {value!r}"
            )
            raise DatabaseRuntimeError(msg)


__all__ = [
    "ConnectionSetting",
    "SettingsProbe",
    "apply_connection_settings",
]
