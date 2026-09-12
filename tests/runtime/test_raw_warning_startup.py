"""Raw declaration safety under actual Python warning startup configurations."""

import asyncio
import sys
from textwrap import dedent

from snektest import Param, assert_eq, test


@test(
    [Param(value="0", name="disabled"), Param(value="1", name="enabled")], mark="slow"
)
async def validated_factory_requires_context_aware_warnings(setting: str) -> None:
    """An unsafe interpreter rejects contracts before calling schema hooks."""

    script = dedent("""
        import sys
        from pydantic import GetCoreSchemaHandler
        from pydantic_core import CoreSchema
        from snekql import mariadb, sqlite

        for namespace in (sqlite, mariadb):
            calls: list[object] = []
            class Contract:
                @classmethod
                def __get_pydantic_core_schema__(cls, source: object, handler: GetCoreSchemaHandler) -> CoreSchema:
                    calls.append(source)
                    return handler.generate_schema(dict[str, int])

            namespace.raw("SELECT 1")
            namespace.raw("SELECT 1", validate=None)
            try:
                namespace.raw("SELECT 1", validate=Contract)
            except namespace.QueryConstructionError as error:
                assert sys.flags.context_aware_warnings == 0
                assert calls == []
                assert "context_aware_warnings" in str(error)
            else:
                assert sys.flags.context_aware_warnings == 1
                assert len(calls) == 1
    """)
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-X",
        f"context_aware_warnings={setting}",
        "-c",
        script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    assert_eq((process.returncode, stdout, stderr), (0, b"", b""))
