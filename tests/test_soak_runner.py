"""The optional soak command reports measured closed-cycle resources."""

import json
import sys

from anyio import run_process
from snektest import assert_eq, test


@test(mark="slow")
async def soak_command_reports_completed_cycles() -> None:
    """An explicit short run must emit a baseline and a final measurement."""
    result = await run_process(
        [
            sys.executable,
            "-m",
            "soak.lifecycle",
            "--backend",
            "sqlite",
            "--cycles",
            "2",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0)
    samples = [json.loads(line) for line in result.stdout.splitlines()]
    assert_eq([sample["cycle"] for sample in samples], [0, 2])
