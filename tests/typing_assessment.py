"""Shared real-checker observations for independently named typing tests."""

import sys
from collections.abc import AsyncGenerator
from copy import deepcopy
from json import loads
from subprocess import CompletedProcess
from typing import Any

from anyio import run_process
from snektest import fixture


class TypingAssessment:
    """Select observations without turning aggregate failure into case failure."""

    def __init__(self, completed: CompletedProcess[bytes]) -> None:
        if completed.returncode not in (0, 1):
            msg = f"Typing CLI failed with status {completed.returncode}: {completed.stderr.decode()}"
            raise AssertionError(msg)
        self._completed = completed
        self._report = loads(completed.stdout)

    @property
    def completed(self) -> CompletedProcess[bytes]:
        """The actual aggregate CLI result, not a fabricated per-case exit code."""
        return deepcopy(self._completed)

    @property
    def report(self) -> dict[str, Any]:
        """A private view of all observations and global diagnostic metadata."""
        return deepcopy(self._report)

    def cases(self, name: str, *, backend: str = "all") -> list[dict[str, Any]]:
        """Return the named observations for the selected backend(s)."""
        if errors := self._report.get("unmapped_errors"):
            msg = f"Unmapped typing diagnostics: {errors}"
            raise AssertionError(msg)
        families = ("sqlite", "mariadb") if backend == "all" else (backend,)
        selected = []
        for family in families:
            matches = [
                case
                for case in self._report["cases"]
                if case["name"] == name and case["backend"] == family
            ]
            if len(matches) != 1:
                msg = f"Expected one typing observation for {name}/{family}; found {len(matches)}"
                raise AssertionError(msg)
            selected.extend(matches)
        return deepcopy(selected)


@fixture(scope="session")
async def provide_typing_assessment() -> AsyncGenerator[TypingAssessment]:
    """Assess unmodified static probes once; mutations/config changes run separately."""
    completed = await run_process(
        [sys.executable, "scripts/check_typing_compatibility.py", "--case", "all"],
        check=False,
    )
    yield TypingAssessment(completed)
