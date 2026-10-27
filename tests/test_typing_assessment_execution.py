"""Shared consumer assessments retain native diagnostics and focused failures."""

import sys
from collections.abc import AsyncGenerator
from json import loads

from anyio import Path, TemporaryDirectory, run_process
from snektest import assert_eq, fixture, load_fixture, test


@fixture
async def provide_batch_checkout() -> AsyncGenerator[Path]:
    """Own the copied CLI, callers and test module used for fault injection."""
    async with TemporaryDirectory(prefix="sq-typing-") as directory:
        root = Path(directory)
        for name in ("scripts", "tests", "typing_probes"):
            await (root / name).mkdir()
        for relative in (
            "scripts/check_typing_compatibility.py",
            "tests/__init__.py",
            "tests/test_typing_guarantees.py",
            "tests/typing_assessment.py",
        ):
            await (root / relative).write_text(await Path(relative).read_text())
        async for source in Path("typing_probes").glob("*.py.txt"):
            await (root / "typing_probes" / source.name).write_text(
                await source.read_text()
            )
        yield root


@test(mark="slow")
async def broken_controls_retain_named_failures() -> None:
    """Control, count, rule and location failures retain their own contract names."""
    root = await load_fixture(provide_batch_checkout())
    positive = root / "typing_probes/temporal-domains.positive.py.txt"
    await positive.write_text(await positive.read_text() + '\ninvalid: int = "wrong"\n')
    for name, challenge in (
        ("select-all", "database.select(Entry).all(); database.select(Entry).all()"),
        ("readonly-scalar", 'invalid: int = "wrong"'),
        ("exists-family", "valid: int = 1"),
        (
            "nullable-expression",
            'valid: int = 1  # expect-error\ninvalid: int = "wrong"',
        ),
    ):
        marked = (
            challenge
            if "# expect-error" in challenge
            else f"{challenge}  # expect-error"
        )
        await (root / f"typing_probes/{name}.negative.py.txt").write_text(
            f"\n\n{marked}\n"
        )

    completed = await run_process(
        [
            sys.executable,
            "-m",
            "snektest",
            "tests/test_typing_guarantees.py",
            "--json-output",
        ],
        cwd=str(root),
        check=False,
    )

    report = loads(completed.stdout)
    assert_eq(completed.returncode, 1, msg=completed.stderr.decode())
    assert_eq(report["passed"], 12)
    assert_eq(report["failed"], 5)
    assert_eq(report["errors"], 0)
    assert_eq(report["fixture_teardown_failed"], 0)
    assert_eq(report["session_teardown_failed"], 0)
    assert_eq(
        {
            case["name"].split("[")[1].removesuffix("]")
            for case in report["tests"]
            if case["status"] == "failed"
        },
        {
            "select-all",
            "temporal-domains",
            "readonly-scalar",
            "exists-family",
            "nullable-expression",
        },
    )


@test(mark="slow")
async def focused_contract_is_independent_of_an_unselected_failure() -> None:
    """Explicit parameter selection still works when another batched case fails."""
    root = await load_fixture(provide_batch_checkout())
    positive = root / "typing_probes/select-all.positive.py.txt"
    await positive.write_text(await positive.read_text() + '\ninvalid: int = "wrong"\n')
    selected = (
        "tests/test_typing_guarantees.py::"
        "public_typing_contract_has_exact_diagnostic[temporal-domains]"
    )

    completed = await run_process(
        [sys.executable, "-m", "snektest", selected, "--json-output"],
        cwd=str(root),
        check=False,
    )

    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
    report = loads(completed.stdout)
    assert_eq(report["passed"], 1)
    assert_eq(report["failed"], 0)
    assert_eq(report["errors"], 0)
    assert_eq(report["fixture_teardown_failed"], 0)
    assert_eq(report["session_teardown_failed"], 0)
    assert_eq([case["name"] for case in report["tests"]], [selected])
