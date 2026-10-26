"""Paired public callers protect typing guarantees through application helpers."""

from snektest import Param, assert_eq, assert_true, load_fixture, test

from tests.typing_assessment import assessed_cases, provide_typing_assessment


@test(
    [
        Param((name, rule), name=name)
        for name, rule in (
            ("select-all", "unresolved-attribute"),
            ("temporal-domains", "invalid-argument-type"),
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
    output = await load_fixture(provide_typing_assessment())
    name, rule = case
    observations = assessed_cases(output, name)
    for observation in observations:
        assert_eq(observation["positive_errors"], [])
        assert_eq(len(observation["negative_errors"]), 1)
        assert_eq(
            observation["negative_errors"][0]["line"], observation["expected_line"]
        )
        assert_eq(observation["negative_errors"][0]["rule"], rule)
        assert_true(observation["conforms"])
