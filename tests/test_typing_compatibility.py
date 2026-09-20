"""Consumer conformance reports through the source-checkout CLI."""

import sys
from collections.abc import AsyncGenerator
from json import loads

from anyio import Path, TemporaryDirectory, run_process
from snektest import Param, assert_eq, assert_true, fixture, load_fixture, test


@fixture
async def provide_probe_checkout() -> AsyncGenerator[Path]:
    """Copy the CLI and source inputs so test mutations never alter the checkout."""
    async with TemporaryDirectory(prefix="snekql-probe-test-") as directory:
        root = Path(directory)
        await (root / "scripts").mkdir()
        await (root / "typing_probes").mkdir()
        for relative in (
            "scripts/check_typing_compatibility.py",
            "typing_probes/lifecycle.positive.py.txt",
            "typing_probes/lifecycle.negative.py.txt",
        ):
            await (root / relative).write_text(await Path(relative).read_text())
        yield root


@test(
    [Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")],
    [Param(name, name=name) for name in ("ty", "pyright", "mypy")],
    mark="fast",
)
async def lifecycle_report_requires_positive_control(
    backend: str, checker: str
) -> None:
    """A generated-id rejection counts only beside correctly inferred states."""
    completed = await run_process(
        [
            sys.executable,
            "scripts/check_typing_compatibility.py",
            "--checker",
            checker,
            "--backend",
            backend,
        ],
        check=False,
    )

    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
    report = loads(completed.stdout)
    assert_eq(report["schema_version"], 1)
    assert_eq(report["checker"], checker)
    assert_true(report["checker_version"].startswith(f"{checker} "))
    assert_eq(len(report["cases"]), 1)
    case = report["cases"][0]
    assert_eq(case["backend"], backend)
    assert_eq(case["name"], "lifecycle")
    assert_eq(case["positive_errors"], [])
    assert_eq(len(case["negative_errors"]), 1)
    assert_eq(case["negative_errors"][0]["line"], case["expected_line"])
    assert_eq(case["conforms"], True)
    assert_eq(report["conforms"], True)


@test(
    [
        Param("positive-error", name="broken-positive-control"),
        Param("missing-negative", name="unrejected-invalid-operation"),
        Param("off-marker", name="unrelated-negative-error"),
    ],
    mark="fast",
)
async def unrelated_errors_cannot_certify_rejection(mutation: str) -> None:
    """Rejecting another line or a broken control cannot satisfy the contract."""
    root = await load_fixture(provide_probe_checkout())
    command = [
        sys.executable,
        str(root / "scripts/check_typing_compatibility.py"),
        "--backend",
        "sqlite",
    ]
    baseline = await run_process(command, check=False)
    assert_eq(baseline.returncode, 0, msg=baseline.stderr.decode())
    if mutation == "positive-error":
        path = root / "typing_probes/lifecycle.positive.py.txt"
        await path.write_text(await path.read_text() + '\ninvalid: int = "wrong"\n')
    else:
        suffix = (
            "\n\ndef requires_generated_id(account: Account[database.Pending]) -> int:\n"
            "    return 0  # expect-error\n"
        )
        if mutation == "off-marker":
            suffix += '\ninvalid: int = "wrong"\n'
        await (root / "typing_probes/lifecycle.negative.py.txt").write_text(suffix)

    completed = await run_process(command, check=False)

    assert_eq(completed.returncode, 1, msg=completed.stderr.decode())
    report = loads(completed.stdout)
    assert_eq(report["conforms"], False)
    assert_eq(report["cases"][0]["conforms"], False)


@test(mark="fast")
async def missing_probe_is_infrastructure_failure() -> None:
    """Missing source input is not reported as checker incompatibility."""
    root = await load_fixture(provide_probe_checkout())
    await (root / "typing_probes/lifecycle.negative.py.txt").unlink()

    completed = await run_process(
        [sys.executable, str(root / "scripts/check_typing_compatibility.py")],
        check=False,
    )

    assert_eq(completed.returncode, 2)
    assert_eq(completed.stdout, b"")
    assert_true(b"typing assessment unavailable" in completed.stderr)


@test([Param(name, name=name) for name in ("ty", "pyright", "mypy")], mark="fast")
async def readiness_probe_requires_explicit_row_scope(checker: str) -> None:
    """A completed query passes while the same unscoped select is diagnosed."""
    completed = await run_process(
        [
            sys.executable,
            "scripts/check_typing_compatibility.py",
            "--checker",
            checker,
            "--case",
            "readiness",
            "--backend",
            "sqlite",
        ],
        check=False,
    )

    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
    report = loads(completed.stdout)
    assert_eq(report["cases"][0]["name"], "readiness")
    assert_eq(report["cases"][0]["conforms"], True)


@test(mark="fast")
async def backend_identity_probe_rejects_cross_family_execution() -> None:
    """Each Transaction rejects an otherwise valid query from the other family."""
    completed = await run_process(
        [
            sys.executable,
            "scripts/check_typing_compatibility.py",
            "--case",
            "backend-identity",
        ],
        check=False,
    )

    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
    report = loads(completed.stdout)
    assert_eq(len(report["cases"]), 2)
    assert_true(all(case["conforms"] for case in report["cases"]))


@test(mark="fast")
async def positional_probe_rejects_ninth_projection() -> None:
    """Eight positional values retain types; a ninth exceeds the public overloads."""
    completed = await run_process(
        [
            sys.executable,
            "scripts/check_typing_compatibility.py",
            "--case",
            "positional-width",
        ],
        check=False,
    )

    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
    assert_true(loads(completed.stdout)["conforms"])


@test(mark="fast")
async def named_probe_preserves_nine_field_result() -> None:
    """Named rows exceed positional width without erasing the result class."""
    completed = await run_process(
        [
            sys.executable,
            "scripts/check_typing_compatibility.py",
            "--case",
            "named-result",
        ],
        check=False,
    )

    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
    assert_true(loads(completed.stdout)["conforms"])


@test(mark="fast")
async def join_probe_retains_nullable_right_model() -> None:
    """Left-join row inference must not silently remove right-side absence."""
    completed = await run_process(
        [sys.executable, "scripts/check_typing_compatibility.py", "--case", "joins"],
        check=False,
    )

    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
    assert_true(loads(completed.stdout)["conforms"])


@test(mark="fast")
async def raw_probe_rejects_consumption_time_validation_override() -> None:
    """A raw statement owns its validated result contract before consumption."""
    completed = await run_process(
        [
            sys.executable,
            "scripts/check_typing_compatibility.py",
            "--case",
            "raw-contract",
        ],
        check=False,
    )

    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
    assert_true(loads(completed.stdout)["conforms"])
