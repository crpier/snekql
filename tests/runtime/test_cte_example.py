"""The documented CTE recipe executes against an actual SQLite database."""

from snektest import assert_eq, test

from examples.typed_ctes import UserSummary, example


@test(mark="medium")
async def typed_cte_recipe_filters_the_named_output() -> None:
    rows = await example()
    assert_eq(rows, [UserSummary(id=3, name="Grace")])
