"""Research-only consumer acceptance at the two confirmed public seams (#606)."""

import json
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TypedDict, cast

from snektest import assert_eq, test

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "research" / "decimal_capabilities_606"


class _Position(TypedDict):
    line: int


class _Positions(TypedDict):
    begin: _Position


class _Location(TypedDict):
    positions: _Positions


class _Diagnostic(TypedDict):
    check_name: str
    description: str
    location: _Location


def _check(source: str, *, overlay: bool = False) -> list[_Diagnostic]:
    with TemporaryDirectory(prefix="snekql606-") as directory:
        work = Path(directory)
        (work / "consumer.py").write_text(source)
        if overlay:
            # The builder copies real package sources, never imports the overlay.
            subprocess.run(
                [
                    str(ROOT / ".venv/bin/python"),
                    str(EVIDENCE / "make_overlay.py"),
                    str(work),
                    "--derived",
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
        result = subprocess.run(
            [
                str(ROOT / ".venv/bin/ty"),
                "check",
                "--project",
                str(work),
                "--python",
                str(ROOT / ".venv"),
                "--python-version",
                "3.15",
                "--extra-search-path",
                str(work if overlay else ROOT),
                "--error",
                "all",
                "--ignore",
                "missing-override-decorator",
                "--output-format",
                "gitlab",
                str(work / "consumer.py"),
            ],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert_eq(result.returncode in (0, 1), True)
        return cast("list[_Diagnostic]", json.loads(result.stdout))


def _expected(source: str) -> list[tuple[int, str]]:
    return [
        (i, match[1])
        for i, line in enumerate(source.splitlines(), 1)
        if (match := re.search(r"# error: ([a-z-]+)", line))
    ]


def _observed(diagnostics: list[_Diagnostic]) -> list[tuple[int, str]]:
    return [
        (d["location"]["positions"]["begin"]["line"], d["check_name"])
        for d in diagnostics
    ]


@test(mark="slow")
def forbidden_operations_and_wrong_values_are_rejected() -> None:
    source = (EVIDENCE / "negative.py.txt").read_text()
    assert_eq(_observed(_check(source, overlay=True)), _expected(source))


@test(mark="slow")
def known_bypasses_and_regressions_remain_explicit() -> None:
    source = (EVIDENCE / "known_holes.py.txt").read_text()
    assert_eq(_observed(_check(source, overlay=True)), _expected(source))


@test(mark="slow")
def baseline_accepts_all_44_forbidden_storage_operations() -> None:
    source = (EVIDENCE / "negative.py.txt").read_text()
    source = source.replace(', Literal["numeric"]', "").replace(', Literal["text"]', "")
    expected = [
        (i, "invalid-argument-type")
        for i, line in enumerate(source.splitlines(), 1)
        if 'eq("not a decimal")' in line
    ]
    assert_eq(_observed(_check(source)), expected)


@test(mark="slow")
def baseline_distinguishes_missing_arithmetic_from_aggregate_regression() -> None:
    source = (EVIDENCE / "known_holes.py.txt").read_text()
    source = source.replace(', Literal["numeric"]', "").replace(', Literal["text"]', "")
    expected = [
        (i, "no-matching-overload")
        for i, line in enumerate(source.splitlines(), 1)
        if '.add(Decimal("1"))' in line
    ]
    assert_eq(_observed(_check(source)), expected)


@test(mark="slow")
def current_annotations_erase_storage_information() -> None:
    source = (EVIDENCE / "baseline.py.txt").read_text()
    assert_eq(_check(source), [])


@test(mark="slow")
def valid_operations_and_exact_result_types_survive() -> None:
    source = (EVIDENCE / "positive.py.txt").read_text()
    assert_eq(_check(source, overlay=True), [])


@test(mark="slow")
def storage_restrictions_survive_a_cte() -> None:
    source = (EVIDENCE / "derived.py.txt").read_text()
    assert_eq(_observed(_check(source, overlay=True)), _expected(source))


@test(mark="slow")
def canonical_text_rejects_ordering() -> None:
    source = (EVIDENCE / "direct.py.txt").read_text()
    diagnostics = _check(source, overlay=True)
    expected_line = next(
        i for i, line in enumerate(source.splitlines(), 1) if "# reject-order" in line
    )
    assert_eq(
        [
            (d["location"]["positions"]["begin"]["line"], d["check_name"])
            for d in diagnostics
        ],
        [(expected_line, "invalid-argument-type")],
    )
