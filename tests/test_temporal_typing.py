"""Concrete temporal meanings remain distinct through public typed helpers."""

from snektest import Param, assert_eq, assert_true, load_fixture, test

from tests.typing_variants import TEMPORAL_EXPRESSIONS, provide_temporal_assessment


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [
        Param((expression, rule), name=name)
        for name, expression, rule in TEMPORAL_EXPRESSIONS
    ],
    mark="slow",
)
async def temporal_meanings_have_exact_negative_diagnostics(
    backend: str, challenge: tuple[str, str]
) -> None:
    """Each rejection has independently clean concrete-result controls."""
    assessment = await load_fixture(provide_temporal_assessment())
    expression, rule = challenge
    observations = assessment.cases(expression, backend=backend)

    assert_eq(len(observations), 1)
    observed = observations[0]
    assert_eq(observed["positive_errors"], [])
    assert_eq(len(observed["negative_errors"]), 1)
    assert_eq(observed["negative_errors"][0]["line"], observed["expected_line"])
    assert_eq(observed["negative_errors"][0]["rule"], rule)
    assert_true(observed["conforms"])
