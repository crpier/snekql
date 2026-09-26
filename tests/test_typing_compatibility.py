"""Consumer conformance reports through the source-checkout CLI."""

import os
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
            "--case",
            "lifecycle",
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
        "--case",
        "lifecycle",
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
async def readiness_report_retains_checker_limits(checker: str) -> None:
    """Only a clean positive control can establish row-scope rejection."""
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

    assert_eq(
        completed.returncode, 0 if checker == "ty" else 1, msg=completed.stderr.decode()
    )
    report = loads(completed.stdout)
    case = report["cases"][0]
    assert_eq(case["name"], "readiness")
    assert_eq(case["conforms"], checker == "ty")
    assert_eq(bool(case["positive_errors"]), checker != "ty")


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


@test([Param(name, name=name) for name in ("ty", "pyright", "mypy")], mark="fast")
async def full_report_preserves_known_checker_limits(checker: str) -> None:
    """Assess every domain on both backends, retaining incompatible controls."""
    completed = await run_process(
        [
            sys.executable,
            "scripts/check_typing_compatibility.py",
            "--checker",
            checker,
            "--case",
            "all",
        ],
        check=False,
    )

    assert_eq(
        completed.returncode,
        0 if checker == "ty" else 1,
        msg=completed.stderr.decode(),
    )
    report = loads(completed.stdout)
    assert_eq(len(report["cases"]), 84)
    failed = {
        (case["backend"], case["name"])
        for case in report["cases"]
        if not case["conforms"]
    }
    unsupported = {
        "ty": (),
        "pyright": (
            "row-constructor",
            "insert-sequence",
            "insert-empty",
            "insert-tuple",
            "source-select",
            "source-row",
            "source-pretender",
            "source-join",
            "source-left-join",
            "source-update",
            "source-delete",
            "source-alias",
            "compare-eq",
            "compare-ne",
            "compare-gt",
            "compare-gte",
            "compare-lt",
            "compare-lte",
            "compare-alias",
            "bulk-destination",
            "bulk-row-state",
            "bulk-backend",
            "bulk-source",
            "read-scope",
            "ready-incomplete",
            "ready-scope",
            "closed-assignment",
            "closed-optional",
            "ready-backend",
            "pending-input",
            "read-constructor",
            "readiness",
            "backend-identity",
            "named-result",
            "joins",
        ),
        "mypy": (
            "frozen-row",
            "frozen-pending",
            "frozen-generated",
            "row-constructor",
            "insert-sequence",
            "insert-empty",
            "insert-tuple",
            "source-select",
            "source-row",
            "source-pretender",
            "source-join",
            "source-left-join",
            "source-update",
            "source-delete",
            "source-alias",
            "compare-eq",
            "compare-ne",
            "compare-gt",
            "compare-gte",
            "compare-lt",
            "compare-lte",
            "compare-alias",
            "bulk-destination",
            "bulk-row-state",
            "bulk-backend",
            "bulk-source",
            "read-scope",
            "ready-incomplete",
            "ready-scope",
            "closed-assignment",
            "closed-optional",
            "ready-backend",
            "pending-input",
            "read-constructor",
            "readiness",
            "backend-identity",
            "positional-width",
            "named-result",
            "joins",
            "fk-defaults",
        ),
    }
    assert_eq(
        failed,
        {
            (backend, name)
            for backend in ("sqlite", "mariadb")
            for name in unsupported[checker]
        },
    )


@test(mark="fast")
async def report_identifies_environment_and_rendered_sources() -> None:
    """A saved assessment identifies its interpreter, checkout and actual inputs."""
    completed = await run_process(
        [
            sys.executable,
            "scripts/check_typing_compatibility.py",
            "--case",
            "lifecycle",
            "--backend",
            "sqlite",
        ],
        check=False,
    )

    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
    report = loads(completed.stdout)
    assert_true(report["recorded_at"].endswith("+00:00"))
    assert_eq(report["environment"]["python"], sys.version)
    assert_true(bool(report["environment"]["platform"]))
    assert_eq(report["environment"]["packages"]["ty"], "0.0.84")
    assert_eq(len(report["environment"]["source_commit"]), 40)
    assert_true(isinstance(report["environment"]["source_dirty"], bool))
    case = report["cases"][0]
    assert_eq(len(case["positive_sha256"]), 64)
    assert_eq(len(case["negative_sha256"]), 64)
    assert_true(case["positive_sha256"] != case["negative_sha256"])


@test(mark="fast")
async def ty_probe_uses_declared_configuration() -> None:
    """An ambient configuration pointer cannot silently change the assessment."""
    completed = await run_process(
        [
            sys.executable,
            "scripts/check_typing_compatibility.py",
            "--case",
            "lifecycle",
        ],
        env={**os.environ, "TY_CONFIG_FILE": "absent-consumer-ty-config.toml"},
        check=False,
    )

    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
    assert_true(loads(completed.stdout)["conforms"])


@test([Param(name, name=name) for name in ("ty", "pyright")], mark="fast")
async def defaulted_fk_probe_preserves_target(checker: str) -> None:
    """Nullable defaults retain constructor inference and reject other targets."""
    completed = await run_process(
        [
            sys.executable,
            "scripts/check_typing_compatibility.py",
            "--checker",
            checker,
            "--case",
            "fk-defaults",
        ],
        check=False,
    )

    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
    assert_true(loads(completed.stdout)["conforms"])


@test(
    [Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")],
    mark="slow",
)
async def row_constructor_requires_valid_pending_control(backend: str) -> None:
    """Only the direct Row call fails beside clean exact-type Pending controls."""
    completed = await run_process(
        [
            sys.executable,
            "scripts/check_typing_compatibility.py",
            "--checker",
            "ty",
            "--case",
            "row-constructor",
            "--backend",
            backend,
        ],
        check=False,
    )

    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
    report = loads(completed.stdout)
    case = report["cases"][0]
    assert_eq(case["positive_errors"], [])
    assert_eq(len(case["negative_errors"]), 1)
    assert_eq(case["negative_errors"][0]["line"], case["expected_line"])
    assert_eq(case["negative_errors"][0]["rule"], "invalid-argument-type")
    assert_true(case["conforms"])


@test(
    [
        Param(name, name=name)
        for name in (
            "bulk-destination",
            "bulk-row-state",
            "bulk-backend",
            "bulk-source",
        )
    ],
    mark="fast",
)
async def explicit_batch_contract_requires_clean_control(name: str) -> None:
    """Each rejection has independent exact-type nonempty and empty controls."""
    completed = await run_process(
        [sys.executable, "scripts/check_typing_compatibility.py", "--case", name],
        check=False,
    )

    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
    report = loads(completed.stdout)
    assert_eq(len(report["cases"]), 2)
    for case in report["cases"]:
        assert_eq(case["positive_errors"], [])
        assert_eq(len(case["negative_errors"]), 1)
        assert_eq(case["negative_errors"][0]["line"], case["expected_line"])
        assert_eq(case["negative_errors"][0]["rule"], "invalid-argument-type")
        assert_true(case["conforms"])


@test(
    [
        Param(name, name=name)
        for name in (
            "read-scope",
            "ready-incomplete",
            "ready-scope",
            "closed-assignment",
            "closed-optional",
            "ready-backend",
            "pending-input",
            "read-constructor",
        )
    ],
    mark="slow",
)
async def read_helper_contract_requires_clean_control(name: str) -> None:
    """Rejected helper usage must have clean exact-type controls on both backends."""
    completed = await run_process(
        [sys.executable, "scripts/check_typing_compatibility.py", "--case", name],
        check=False,
    )

    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
    report = loads(completed.stdout)
    assert_eq(len(report["cases"]), 2)
    expected_rule = {
        "read-scope": "invalid-argument-type",
        "ready-incomplete": "no-matching-overload",
        "ready-scope": "no-matching-overload",
        "closed-assignment": "invalid-assignment",
        "closed-optional": "no-matching-overload",
        "ready-backend": "no-matching-overload",
        "pending-input": "invalid-argument-type",
        "read-constructor": "call-non-callable",
    }[name]
    for case in report["cases"]:
        assert_eq(case["positive_errors"], [])
        assert_eq(len(case["negative_errors"]), 1)
        assert_eq(case["negative_errors"][0]["line"], case["expected_line"])
        assert_eq(case["negative_errors"][0]["rule"], expected_rule)
        assert_true(case["conforms"])


@test(
    [
        Param((name, rule), name=name)
        for name, rule in (
            ("compare-eq", "invalid-argument-type"),
            ("compare-ne", "invalid-argument-type"),
            ("compare-gt", "invalid-argument-type"),
            ("compare-gte", "invalid-argument-type"),
            ("compare-lt", "invalid-argument-type"),
            ("compare-lte", "invalid-argument-type"),
            ("compare-alias", "no-matching-overload"),
            ("frozen-row", "invalid-assignment"),
            ("frozen-pending", "invalid-assignment"),
            ("frozen-generated", "invalid-assignment"),
        )
    ],
    mark="slow",
)
async def comparison_or_freezing_requires_clean_control(case: tuple[str, str]) -> None:
    """Check one invalid operation beside exact-type valid callers on each backend."""
    name, rule = case
    completed = await run_process(
        [sys.executable, "scripts/check_typing_compatibility.py", "--case", name],
        check=False,
    )

    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
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


@test(
    [
        Param(verb, name=verb)
        for verb in (
            "select",
            "row",
            "pretender",
            "join",
            "left-join",
            "update",
            "delete",
            "alias",
        )
    ],
    mark="slow",
)
async def query_source_contract_requires_clean_control(verb: str) -> None:
    """Nominal guards reject values without losing native query role result types."""
    completed = await run_process(
        [
            sys.executable,
            "scripts/check_typing_compatibility.py",
            "--case",
            f"source-{verb}",
        ],
        check=False,
    )

    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
    report = loads(completed.stdout)
    assert_eq(len(report["cases"]), 2)
    for observation in report["cases"]:
        assert_eq(observation["positive_errors"], [])
        assert_eq(len(observation["negative_errors"]), 1)
        assert_eq(
            observation["negative_errors"][0]["line"], observation["expected_line"]
        )
        assert_eq(
            observation["negative_errors"][0]["rule"],
            "invalid-argument-type"
            if verb in {"update", "delete"}
            else "no-matching-overload",
        )
        assert_true(observation["conforms"])


@test(
    [Param(kind, name=kind) for kind in ("sequence", "empty", "tuple")],
    mark="slow",
)
async def single_insert_contract_requires_clean_control(kind: str) -> None:
    """Sequence rejection accompanies exact single/batch RETURNING controls."""
    completed = await run_process(
        [
            sys.executable,
            "scripts/check_typing_compatibility.py",
            "--case",
            f"insert-{kind}",
        ],
        check=False,
    )

    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
    report = loads(completed.stdout)
    assert_eq(len(report["cases"]), 2)
    for observation in report["cases"]:
        assert_eq(observation["positive_errors"], [])
        assert_eq(len(observation["negative_errors"]), 1)
        assert_eq(
            observation["negative_errors"][0]["line"], observation["expected_line"]
        )
        assert_eq(observation["negative_errors"][0]["rule"], "invalid-argument-type")
        assert_true(observation["conforms"])
