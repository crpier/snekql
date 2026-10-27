"""Backend identity survives public nested-expression composition."""

from snektest import Param, assert_eq, assert_true, load_fixture, test

from tests.typing_variants import NESTED_EXPRESSIONS, provide_nested_assessment


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [
        Param((expression, rule), name=name)
        for name, expression, rule in NESTED_EXPRESSIONS
    ],
    mark="slow",
)
async def nested_expression_rejects_foreign_family(
    backend: str, challenge: tuple[str, str]
) -> None:
    """One invalid composition fails beside exact public helper controls."""
    assessment = await load_fixture(provide_nested_assessment())
    expression, rule = challenge
    observations = assessment.cases(expression, backend=backend)

    assert_eq(len(observations), 1)
    observed = observations[0]
    assert_eq(observed["positive_errors"], [])
    assert_eq(len(observed["negative_errors"]), 1)
    assert_eq(observed["negative_errors"][0]["line"], observed["expected_line"])
    assert_eq(observed["negative_errors"][0]["rule"], rule)
    assert_true(observed["conforms"])
