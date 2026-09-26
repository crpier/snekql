"""Concrete temporal meanings remain distinct through public typed helpers."""

import sys
from json import loads

from anyio import Path, run_process
from snektest import Param, assert_eq, assert_true, load_fixture, test

from tests.test_typing_compatibility import provide_probe_checkout


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [
        Param((expression, rule), name=name)
        for name, expression, rule in (
            (
                "raw-datetime",
                "Event.instant.eq(datetime(2026, 1, 1, tzinfo=UTC))",
                "invalid-argument-type",
            ),
            ("column", "Event.instant.eq_col(Event.civil)", "no-matching-overload"),
            (
                "membership",
                "Event.instant.in_subquery(database.select(Event.civil))",
                "invalid-argument-type",
            ),
            (
                "readonly",
                "instant_column(Event.instant).eq(civil)",
                "invalid-argument-type",
            ),
            ("assignment", "Event.instant.to(civil)", "no-matching-overload"),
            ("cte", "derived.column(token).eq(civil)", "invalid-argument-type"),
            (
                "alias",
                "aliased.column(Event.instant).eq(civil)",
                "invalid-argument-type",
            ),
            ("aggregate", "Event.instant.min().eq(civil)", "invalid-argument-type"),
            (
                "scalar",
                "Event.instant.eq_col(database.scalar(database.select(Event.civil)))",
                "no-matching-overload",
            ),
            ("constructor", "database.UtcDatetime(civil)", "invalid-argument-type"),
            ("result", "wrong: database.LocalDatetime = instant", "invalid-assignment"),
        )
    ],
    mark="slow",
)
async def temporal_meanings_have_exact_negative_diagnostics(
    backend: str, challenge: tuple[str, str]
) -> None:
    """Each rejection has independently clean concrete-result controls."""
    expression, rule = challenge
    root = await load_fixture(provide_probe_checkout())
    expression, rule = challenge
    case = "temporal-domains"
    await (root / "typing_probes" / f"{case}.positive.py.txt").write_text(
        await Path(f"typing_probes/{case}.positive.py.txt").read_text()
    )
    await (root / "typing_probes" / f"{case}.negative.py.txt").write_text(
        f"\n\n{expression}  # expect-error\n"
    )

    completed = await run_process(
        [
            sys.executable,
            str(root / "scripts/check_typing_compatibility.py"),
            "--case",
            case,
            "--backend",
            backend,
        ],
        check=False,
    )

    report = loads(completed.stdout)
    assert_eq(len(report["cases"]), 1)
    observed = report["cases"][0]
    assert_eq(observed["positive_errors"], [])
    assert_eq(len(observed["negative_errors"]), 1)
    assert_eq(observed["negative_errors"][0]["line"], observed["expected_line"])
    assert_eq(observed["negative_errors"][0]["rule"], rule)
    assert_true(observed["conforms"])
    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
