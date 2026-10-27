"""Explicit batch inputs keep real checker evidence attributable to each variant."""

import sys
from hashlib import sha256
from json import dumps

from anyio import Path, TemporaryDirectory, run_process
from snektest import Param, assert_eq, assert_true, load_fixture, test

from tests.typing_assessment import TypingAssessment
from tests.typing_variants import (
    NESTED_EXPRESSIONS,
    TEMPORAL_EXPRESSIONS,
    provide_nested_assessment,
    provide_temporal_assessment,
)


@test(mark="slow")
async def batch_reports_each_distinct_input_with_its_own_control() -> None:
    """Two independent negative modules retain their own locations and hashes."""
    positive = "value: int = 1\n"
    requests = [
        {
            "name": "assignment",
            "backend": "sqlite",
            "positive": positive,
            "negative": "\nwrong: str = value  # expect-error\n",
        },
        {
            "name": "list-assignment",
            "backend": "sqlite",
            "positive": positive,
            "negative": "\nwrong: list[str] = value  # expect-error\n",
        },
    ]
    async with TemporaryDirectory(prefix="typing-batch-") as directory:
        manifest = Path(directory) / "requests.json"
        await manifest.write_text(dumps({"schema_version": 1, "cases": requests}))
        completed = await run_process(
            [
                sys.executable,
                "scripts/check_typing_compatibility.py",
                "--manifest",
                str(manifest),
            ],
            check=False,
        )
    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
    assessment = TypingAssessment(completed)
    assert_eq(len(assessment.report["cases"]), 2)
    for request in requests:
        observation = assessment.cases(request["name"], backend="sqlite")[0]
        assert_eq(observation["positive_errors"], [])
        assert_eq(len(observation["negative_errors"]), 1)
        assert_eq(observation["negative_errors"][0]["rule"], "invalid-assignment")
        assert_eq(observation["negative_errors"][0]["line"], 3)
        assert_eq(observation["expected_line"], 3)
        assert_eq(observation["positive_sha256"], sha256(positive.encode()).hexdigest())
        assert_eq(
            observation["negative_sha256"],
            sha256((positive + request["negative"]).encode()).hexdigest(),
        )
        assert_true(observation["conforms"])
    assert_eq(assessment.report["unmapped_errors"], [])


@test(mark="slow")
async def duplicate_batch_identity_is_an_infrastructure_error() -> None:
    """Repeated name/backend keys must not overwrite or multiply evidence."""
    request = {
        "name": "same",
        "backend": "sqlite",
        "positive": "value = 1\n",
        "negative": "wrong: str = value  # expect-error\n",
    }
    async with TemporaryDirectory(prefix="typing-batch-") as directory:
        manifest = Path(directory) / "requests.json"
        await manifest.write_text(
            dumps({"schema_version": 1, "cases": [request, request]})
        )
        completed = await run_process(
            [
                sys.executable,
                "scripts/check_typing_compatibility.py",
                "--manifest",
                str(manifest),
            ],
            check=False,
        )
    assert_eq(completed.returncode, 2, msg=completed.stderr.decode())
    assert_eq(completed.stdout, b"")


@test(mark="slow")
async def focused_selection_does_not_assess_an_unrelated_broken_variant() -> None:
    """A narrow name/backend request excludes even a malformed other fragment."""
    requests = [
        {
            "name": "wanted",
            "backend": "sqlite",
            "positive": "value = 1\n",
            "negative": "wrong: str = value  # expect-error\n",
        },
        {
            "name": "wanted",
            "backend": "mariadb",
            "positive": "value = 1\n",
            "negative": "no expected marker",
        },
        {
            "name": "other",
            "backend": "sqlite",
            "positive": "",
            "negative": "no expected marker",
        },
    ]
    async with TemporaryDirectory(prefix="typing-batch-") as directory:
        manifest = Path(directory) / "requests.json"
        await manifest.write_text(dumps({"schema_version": 1, "cases": requests}))
        completed = await run_process(
            [
                sys.executable,
                "scripts/check_typing_compatibility.py",
                "--manifest",
                str(manifest),
                "--name",
                "wanted",
                "--backend",
                "sqlite",
            ],
            check=False,
        )
    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
    assessment = TypingAssessment(completed)
    assert_eq(len(assessment.report["cases"]), 1)
    assert_true(assessment.cases("wanted", backend="sqlite")[0]["conforms"])


@test(mark="slow")
async def broken_variant_does_not_poison_a_healthy_variant_on_the_same_backend() -> (
    None
):
    """Positive-control failures and missing rejections retain exact ownership."""
    requests = [
        {
            "name": "healthy",
            "backend": "sqlite",
            "positive": "value: int = 1\n",
            "negative": "wrong: str = value  # expect-error\n",
        },
        {
            "name": "broken-control",
            "backend": "sqlite",
            "positive": "value: int = 'bad'\n",
            "negative": "wrong: str = value  # expect-error\n",
        },
        {
            "name": "missing-rejection",
            "backend": "sqlite",
            "positive": "value: int = 1\n",
            "negative": "right: int = value  # expect-error\n",
        },
    ]
    async with TemporaryDirectory(prefix="typing-batch-") as directory:
        manifest = Path(directory) / "requests.json"
        await manifest.write_text(dumps({"schema_version": 1, "cases": requests}))
        completed = await run_process(
            [
                sys.executable,
                "scripts/check_typing_compatibility.py",
                "--manifest",
                str(manifest),
            ],
            check=False,
        )
    assert_eq(completed.returncode, 1, msg=completed.stderr.decode())
    assessment = TypingAssessment(completed)
    assert_eq(assessment.completed.returncode, 1)
    assert_eq(assessment.report["conforms"], False)
    healthy = assessment.cases("healthy", backend="sqlite")[0]
    assert_true(healthy["conforms"])
    assert_eq(healthy["positive_errors"], [])
    assert_eq(len(healthy["negative_errors"]), 1)
    assert_eq(healthy["negative_errors"][0]["rule"], "invalid-assignment")
    assert_eq(healthy["negative_errors"][0]["line"], healthy["expected_line"])
    broken = assessment.cases("broken-control", backend="sqlite")[0]
    assert_true(bool(broken["positive_errors"]))
    assert_eq(broken["conforms"], False)
    missing = assessment.cases("missing-rejection", backend="sqlite")[0]
    assert_eq(missing["positive_errors"], [])
    assert_eq(missing["negative_errors"], [])
    assert_eq(missing["conforms"], False)


@test(
    [
        Param(("{", []), name="invalid-json"),
        Param((dumps({"schema_version": 1, "cases": []}), []), name="empty-batch"),
        Param((dumps({"schema_version": 2, "cases": []}), []), name="unknown-schema"),
        Param((None, ["--name", "absent"]), name="missing-name"),
        Param((None, ["--backend", "mariadb"]), name="missing-backend"),
        Param((None, ["--case", "lifecycle"]), name="conflicting-modes"),
        Param(
            (
                dumps(
                    {
                        "schema_version": 1,
                        "cases": [
                            {
                                "name": "no-marker",
                                "backend": "sqlite",
                                "positive": "",
                                "negative": "pass",
                            }
                        ],
                    }
                ),
                [],
            ),
            name="missing-marker",
        ),
        Param(
            (
                dumps(
                    {
                        "schema_version": 1,
                        "cases": [
                            {
                                "name": "two-markers",
                                "backend": "sqlite",
                                "positive": "# expect-error\n",
                                "negative": "# expect-error\n",
                            }
                        ],
                    }
                ),
                [],
            ),
            name="multiple-markers",
        ),
    ],
    mark="slow",
)
async def invalid_batch_cannot_emit_a_success_report(
    selection: tuple[str | None, list[str]],
) -> None:
    """Malformed or empty selections stay infrastructure/usage errors, not passes."""
    content, options = selection
    if content is None:
        content = dumps(
            {
                "schema_version": 1,
                "cases": [
                    {
                        "name": "present",
                        "backend": "sqlite",
                        "positive": "value=1\n",
                        "negative": "wrong: str = value # expect-error\n",
                    }
                ],
            }
        )
    async with TemporaryDirectory(prefix="typing-batch-") as directory:
        manifest = Path(directory) / "requests.json"
        await manifest.write_text(content)
        completed = await run_process(
            [
                sys.executable,
                "scripts/check_typing_compatibility.py",
                "--manifest",
                str(manifest),
                *options,
            ],
            check=False,
        )
    assert_eq(completed.returncode, 2, msg=completed.stderr.decode())
    assert_eq(completed.stdout, b"")
    assert_true(bool(completed.stderr))


@test([Param("nested", name="nested"), Param("temporal", name="temporal")], mark="slow")
async def batch_certifies_every_declared_variant_and_aggregate_status(
    group: str,
) -> None:
    """No omitted/extra/duplicated entry or global failure can hide in named views."""
    assessment = await load_fixture(
        provide_nested_assessment()
        if group == "nested"
        else provide_temporal_assessment()
    )
    variants = NESTED_EXPRESSIONS if group == "nested" else TEMPORAL_EXPRESSIONS
    completed = assessment.completed
    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
    report = assessment.report
    expected = {
        (expression, backend)
        for _, expression, _ in variants
        for backend in ("sqlite", "mariadb")
    }
    observed = [(case["name"], case["backend"]) for case in report["cases"]]
    assert_eq(set(observed), expected)
    assert_eq(len(observed), len(expected))
    assert_eq(report["unmapped_errors"], [])
    assert_true(report["conforms"])
