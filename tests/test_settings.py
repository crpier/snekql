"""Unit tests for the backend-neutral connection settings seam."""

from __future__ import annotations

from snektest import assert_eq, assert_raises, assert_true, test

from snekql._settings import ConnectionSetting, apply_connection_settings
from snekql.errors import DatabaseRuntimeError


class _FakeProbe:
    """Records executed statements and answers probes from a canned mapping."""

    def __init__(self, values: dict[str, object]) -> None:
        self.values: dict[str, object] = values
        self.executed: list[str] = []

    async def execute(self, sql: str) -> None:
        self.executed.append(sql)

    async def fetch_value(self, sql: str) -> object:
        return self.values[sql]


@test(mark="fast")
async def apply_runs_statements_then_verifies_expected_value() -> None:
    """Each setting applies its statements before its value is read back."""

    probe = _FakeProbe({"PRAGMA foreign_keys": 1})
    setting = ConnectionSetting(
        name="foreign_keys",
        apply_statements=("PRAGMA foreign_keys = ON",),
        probe_sql="PRAGMA foreign_keys",
        expected_value=1,
    )

    await apply_connection_settings(probe, [setting], backend="sqlite")

    assert_eq(probe.executed, ["PRAGMA foreign_keys = ON"])


@test(mark="fast")
async def apply_raises_when_setting_did_not_take_effect() -> None:
    """A silently ignored setting fails fast with the backend and name named."""

    probe = _FakeProbe({"PRAGMA foreign_keys": 0})
    setting = ConnectionSetting(
        name="foreign_keys",
        apply_statements=("PRAGMA foreign_keys = ON",),
        probe_sql="PRAGMA foreign_keys",
        expected_value=1,
        expectation="1 (ON)",
    )

    with assert_raises(DatabaseRuntimeError) as caught:
        await apply_connection_settings(probe, [setting], backend="sqlite")

    message = str(caught.exception)
    assert_true("sqlite" in message)
    assert_true("foreign_keys" in message)
    assert_true("1 (ON)" in message)


@test(mark="fast")
async def apply_accepts_a_predicate_for_compound_values() -> None:
    """A predicate setting verifies derived facts such as flag membership."""

    probe = _FakeProbe({"SELECT @@SESSION.sql_mode": "STRICT_ALL_TABLES,NO_ZERO_DATE"})
    setting = ConnectionSetting(
        name="sql_mode",
        apply_statements=("SET SESSION sql_mode = 'STRICT_ALL_TABLES'",),
        probe_sql="SELECT @@SESSION.sql_mode",
        predicate=lambda value: "STRICT_ALL_TABLES" in str(value),
    )

    await apply_connection_settings(probe, [setting], backend="mariadb")

    assert_eq(probe.executed, ["SET SESSION sql_mode = 'STRICT_ALL_TABLES'"])


@test(mark="fast")
async def verify_only_settings_run_no_statements() -> None:
    """A setting with no apply statements only reads its value back."""

    probe = _FakeProbe({"PRAGMA encoding": "UTF-8"})
    setting = ConnectionSetting(
        name="encoding",
        probe_sql="PRAGMA encoding",
        expected_value="UTF-8",
    )

    await apply_connection_settings(probe, [setting], backend="sqlite")

    assert_eq(probe.executed, [])
