"""One session-owned CLI report for immutable consumer typing contracts."""

import sys
from collections.abc import AsyncGenerator
from json import loads
from typing import Any

from anyio import run_process
from snektest import assert_eq, assert_true, fixture


@fixture(scope="session")
async def provide_typing_assessment() -> AsyncGenerator[bytes]:
    """Keep immutable wire bytes; each consumer parses an independent report."""
    completed = await run_process(
        [sys.executable, "scripts/check_typing_compatibility.py"], check=False
    )
    # Exit 1 still carries usable, case-local evidence. Do not turn one rejected
    # contract into a shared fixture error for every independently named test.
    assert_true(completed.returncode in (0, 1), msg=completed.stderr.decode())
    yield completed.stdout


def assessed_cases(
    output: bytes, name: str, backend: str = "all"
) -> list[dict[str, Any]]:
    """Select native observations without replacing or weakening their diagnostics."""
    report = loads(output)
    assert_eq(report["unmapped_errors"], [])
    observations = [
        case
        for case in report["cases"]
        if case["name"] == name and (backend == "all" or case["backend"] == backend)
    ]
    expected_backends = {"sqlite", "mariadb"} if backend == "all" else {backend}
    assert_eq(len(observations), len(expected_backends))
    assert_eq({case["backend"] for case in observations}, expected_backends)
    return observations
