"""Shared report consumers retain diagnostic ownership and isolated views."""

import sys
from json import dumps
from subprocess import CompletedProcess

from anyio import Path as AsyncPath
from anyio import TemporaryDirectory, run_process
from snektest import Param, assert_eq, assert_in, assert_raises, assert_true, test

from tests.typing_assessment import TypingAssessment


def example_assessment() -> TypingAssessment:
    """A literal checker report with distinguishable backend/case observations."""
    return TypingAssessment(
        CompletedProcess(
            args=["typing-cli"],
            returncode=0,
            stdout=dumps(
                {
                    "conforms": True,
                    "cases": [
                        {"name": "lifecycle", "backend": "sqlite", "conforms": True},
                        {
                            "name": "row-constructor",
                            "backend": "sqlite",
                            "conforms": True,
                        },
                        {"name": "lifecycle", "backend": "mariadb", "conforms": True},
                    ],
                }
            ).encode(),
            stderr=b"",
        )
    )


@test(mark="fast")
def lookup_selects_the_named_backend_observation() -> None:
    """A selected backend cannot inherit a different case's evidence."""
    assessment = example_assessment()
    assert_eq(
        assessment.cases("lifecycle", backend="mariadb"),
        [{"name": "lifecycle", "backend": "mariadb", "conforms": True}],
    )


@test(
    [
        Param(("absent", "sqlite"), name="missing-name"),
        Param(("row-constructor", "all"), name="missing-second-backend"),
        Param(("lifecycle", "other"), name="unknown-backend"),
    ],
    mark="fast",
)
def missing_observation_cannot_pass_vacuously(selection: tuple[str, str]) -> None:
    """An empty or incomplete view is not evidence of checker conformance."""
    name, backend = selection
    assessment = example_assessment()
    with assert_raises(AssertionError) as error:
        assessment.cases(name, backend=backend)
    assert_in(name, str(error.exception))


@test(mark="fast")
def duplicate_observations_are_not_silently_selected() -> None:
    """Ambiguous ownership cannot silently choose one diagnostic record."""
    case = {"name": "lifecycle", "backend": "sqlite", "conforms": True}
    assessment = TypingAssessment(
        CompletedProcess(
            args=["typing-cli"],
            returncode=0,
            stdout=dumps({"cases": [case, case]}).encode(),
            stderr=b"",
        )
    )
    with assert_raises(AssertionError) as error:
        assessment.cases("lifecycle", backend="sqlite")
    assert_in("lifecycle/sqlite", str(error.exception))


@test(mark="fast")
def consumer_mutation_cannot_change_the_next_observation() -> None:
    """A test changing its result view cannot corrupt later named checks."""
    assessment = example_assessment()
    selected = assessment.cases("lifecycle", backend="sqlite")
    selected[0]["conforms"] = False
    assert_eq(assessment.cases("lifecycle", backend="sqlite")[0]["conforms"], True)


@test(mark="slow")
async def failed_backend_does_not_poison_a_clean_observation() -> None:
    """A real broken positive control fails only its own backend's lookup."""
    async with TemporaryDirectory(prefix="typing-lookup-") as directory:
        root = AsyncPath(directory)
        await (root / "scripts").mkdir()
        await (root / "typing_probes").mkdir()
        for relative in (
            "scripts/check_typing_compatibility.py",
            "typing_probes/lifecycle.positive.py.txt",
            "typing_probes/lifecycle.negative.py.txt",
        ):
            await (root / relative).write_text(await AsyncPath(relative).read_text())
        positive = root / "typing_probes/lifecycle.positive.py.txt"
        await positive.write_text(
            await positive.read_text()
            + "\nfrom snekql import sqlite\n"
            + 'mismatch: sqlite.Config = database.Config(database=":memory:")\n'
        )
        completed = await run_process(
            [
                sys.executable,
                str(root / "scripts/check_typing_compatibility.py"),
                "--case",
                "lifecycle",
            ],
            check=False,
        )
    assert_eq(completed.returncode, 1, msg=completed.stderr.decode())
    assessment = TypingAssessment(completed)
    assert_eq(assessment.completed.returncode, 1)
    assert_eq(assessment.report["conforms"], False)
    healthy = assessment.cases("lifecycle", backend="sqlite")[0]
    assert_eq(healthy["positive_errors"], [])
    assert_eq(len(healthy["negative_errors"]), 1)
    assert_eq(healthy["negative_errors"][0]["line"], healthy["expected_line"])
    assert_true(healthy["conforms"])
    broken = assessment.cases("lifecycle", backend="mariadb")[0]
    assert_true(bool(broken["positive_errors"]))
    assert_eq(broken["conforms"], False)


@test(mark="fast")
def infrastructure_failure_is_not_an_empty_assessment() -> None:
    """Unavailable checker evidence is an explicit setup failure, not no cases."""
    with assert_raises(AssertionError) as error:
        TypingAssessment(
            CompletedProcess(
                args=["typing-cli"],
                returncode=2,
                stdout=b"",
                stderr=b"typing assessment unavailable: missing probe",
            )
        )
    assert_in("missing probe", str(error.exception))


@test(mark="fast")
def unowned_diagnostics_cannot_certify_a_clean_case() -> None:
    """An error outside the case files has unknown scope and must stay visible."""
    assessment = TypingAssessment(
        CompletedProcess(
            args=["typing-cli"],
            returncode=1,
            stdout=dumps(
                {
                    "cases": [
                        {"name": "lifecycle", "backend": "sqlite", "conforms": True}
                    ],
                    "unmapped_errors": [
                        {"file": "dependency.py", "message": "broken dependency"}
                    ],
                }
            ).encode(),
            stderr=b"",
        )
    )
    with assert_raises(AssertionError) as error:
        assessment.cases("lifecycle", backend="sqlite")
    assert_in("broken dependency", str(error.exception))
