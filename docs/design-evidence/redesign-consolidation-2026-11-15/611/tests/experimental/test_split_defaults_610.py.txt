"""Issue #610: real-package static declarations; never execute the copied package."""

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TypedDict, cast

from snektest import Param, assert_eq, test

from research.split_defaults_610.make_overlay import build_overlay

RESEARCH = Path(__file__).resolve().parents[2] / "research" / "split_defaults_610"


class Position(TypedDict):
    """Location from ty's JSON output, not a consumer value."""

    line: int


class Positions(TypedDict):
    """GitLab JSON position pair."""

    begin: Position


class Location(TypedDict):
    """Primary diagnostic location."""

    path: str
    positions: Positions


class Diagnostic(TypedDict):
    """The subset of the external checker response inspected by the harness."""

    check_name: str
    location: Location


def check_case(
    backend: str, case: str, *, modified: bool = True, positive_only: bool = False
) -> None:
    """Require exact diagnostics from imported models and their consumers."""
    with TemporaryDirectory(prefix="snekql-split-610-") as directory:
        root = Path(directory)
        build_overlay(root, modified=modified)
        expected: list[tuple[str, int, str]] = []
        paths: list[str] = []
        for suffix in ("models", "consumer"):
            name = f"{suffix}.py"
            source = (
                (RESEARCH / f"{case}.{suffix}.py.txt")
                .read_text()
                .replace("__BACKEND__", backend)
            )
            lines = source.splitlines()
            if positive_only:
                lines = ["" if "# error: " in line else line for line in lines]
            (root / name).write_text("\n".join(lines) + "\n")
            paths.append(name)
            for number, line in enumerate(lines, 1):
                if "# error: " in line:
                    expected.extend(
                        (name, number, code.strip())
                        for code in line.split("# error: ")[1].split(",")
                    )
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "ty",
                "check",
                "--python",
                sys.executable,
                "--output-format",
                "gitlab",
                *paths,
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode in (0, 1), completed.stderr
        diagnostics = cast("list[Diagnostic]", json.loads(completed.stdout))
        actual = [
            (
                str((root / item["location"]["path"]).relative_to(root)),
                item["location"]["positions"]["begin"]["line"],
                item["check_name"],
            )
            for item in diagnostics
        ]
        assert_eq(sorted(actual), sorted(expected))
        assert_eq(completed.returncode, int(bool(expected)))


@test([Param(backend, name=backend) for backend in ("sqlite", "mariadb")], mark="slow")
def baseline_does_not_have_the_proposed_sql_parameter(backend: str) -> None:
    """The unmodified imported package rejects the anchor spelling on the exact line."""
    check_case(backend, "baseline", modified=False)


@test([Param(backend, name=backend) for backend in ("sqlite", "mariadb")], mark="slow")
def python_default_coexists_with_independent_sql_default(backend: str) -> None:
    """A Python default permits omission without changing the logical value type."""
    check_case(backend, "python_default")


@test([Param(backend, name=backend) for backend in ("sqlite", "mariadb")], mark="slow")
def explicit_python_default_alone_controls_omission(backend: str) -> None:
    """A SQL fallback never makes required input optional; GenCol alone doesn't either."""
    check_case(backend, "construction", positive_only=True)
    check_case(backend, "construction")


@test([Param(backend, name=backend) for backend in ("sqlite", "mariadb")], mark="slow")
def python_factory_and_default_domains_remain_precise(backend: str) -> None:
    """Factories permit omission but bad Python defaults must not certify a str field."""
    check_case(backend, "factory", positive_only=True)
    check_case(backend, "factory")


@test([Param(backend, name=backend) for backend in ("sqlite", "mariadb")], mark="slow")
def public_queries_keep_complete_rows_and_marker_free_values(backend: str) -> None:
    """SELECT and RETURNING do not leak pending markers into successful result types."""
    check_case(backend, "queries", positive_only=True)
    check_case(backend, "queries")
