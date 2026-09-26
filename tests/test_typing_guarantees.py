"""Paired public callers protect typing guarantees through application helpers."""

import sys
from json import loads

from anyio import run_process
from snektest import Param, assert_eq, assert_true, test


@test(
    [
        Param((name, rule), name=name)
        for name, rule in (
            ("readonly-scalar", "no-matching-overload"),
            ("scalar-outer-scope", "no-matching-overload"),
            ("exists-outer-scope", "invalid-argument-type"),
            ("nullable-expression", "invalid-argument-type"),
            ("write-validation", "invalid-assignment"),
            ("returning-domain", "invalid-assignment"),
            ("exists-family", "invalid-argument-type"),
            ("nested-exists-family", "invalid-argument-type"),
            ("nested-scalar-family", "no-matching-overload"),
            ("nested-membership-family", "invalid-argument-type"),
            ("nested-projection-family", "invalid-argument-type"),
            ("nested-fk-family", "invalid-argument-type"),
            ("nested-helper-family", "invalid-argument-type"),
            ("not-exists-family", "invalid-argument-type"),
            ("scalar-family", "invalid-argument-type"),
        )
    ],
    mark="slow",
)
async def public_typing_contract_has_exact_diagnostic(case: tuple[str, str]) -> None:
    """Reject only the invalid operation beside exact inferred-type controls."""
    name, rule = case
    completed = await run_process(
        [
            sys.executable,
            "scripts/check_typing_compatibility.py",
            "--case",
            name,
        ],
        check=False,
    )

    report = loads(completed.stdout)
    assert_eq(len(report["cases"]), 2)
    for observation in report["cases"]:
        assert_eq(observation["positive_errors"], [])
        assert_eq(len(observation["negative_errors"]), 1)
        assert_eq(
            observation["negative_errors"][0]["line"], observation["expected_line"]
        )
        assert_eq(observation["negative_errors"][0]["rule"], rule)
        assert_true(observation["conforms"])
    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
