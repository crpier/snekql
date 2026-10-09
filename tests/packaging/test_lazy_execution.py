"""Fresh-process public contracts under Python's forced-lazy import flag."""

lazy import sys

lazy from anyio import run_process
lazy from snektest import Param, assert_eq, test


@test(
    [Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")],
    mark="slow",
)
async def forced_lazy_query_inspection(backend: str) -> None:
    """A fresh backend can compile a query without implicit import side effects."""
    script = f"""
lazy from typing import ClassVar
lazy from snekql import {backend} as database

class Account[S = database.Pending](database.Model[S]):
    __row_type__: ClassVar[database.ReadType[Account[database.Row]]]
    id: Account.Col[int] = database.Integer(primary_key=True)

compiled = database.select(Account.id).where(Account.id.eq(7)).compile()
assert "SELECT" in compiled.sql
assert compiled.params == (7,)
"""

    completed = await run_process(
        [sys.executable, "-X", "lazy_imports=all", "-c", script], check=False
    )

    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())


@test(mark="slow")
async def forced_lazy_config_validation() -> None:
    """Runtime validation must reject invalid values, not accept lazy proxies."""
    script = """
lazy from snekql import sqlite
try:
    sqlite.Config(database=":memory:", pool_size=-1)
except sqlite.DatabaseRuntimeError:
    pass
else:
    raise AssertionError("invalid pool size bypassed validation")
"""

    completed = await run_process(
        [sys.executable, "-X", "lazy_imports=all", "-c", script], check=False
    )

    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())


@test(mark="slow")
async def documentation_help_defers_backend_loading() -> None:
    """Documentation-only invocations do not initialize query/runtime modules."""
    script = """
lazy import sys
lazy from snekql.cli import main
assert main(["--help"]) == 0
assert "snekql.sqlite" not in sys.modules
assert "snekql.mariadb" not in sys.modules
"""

    completed = await run_process(
        [sys.executable, "-X", "lazy_imports=all", "-c", script], check=False
    )

    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
