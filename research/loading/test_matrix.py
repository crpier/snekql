"""Independent specification literals across all recorded application strategies."""

from collections.abc import AsyncGenerator
from typing import Any

from snektest import Param, assert_eq, assert_is_none, fixture, load_fixture, test

from research.loading.experiment import configurations, observe


@fixture(scope="session")
async def observations() -> AsyncGenerator[dict[tuple[str, str], dict[str, Any]]]:
    """Reuse completed observations, never warm sessions or mutable application state."""
    yield {case: await observe(*case) for case in configurations()}


CASES = [Param(value=case, name="-".join(case)) for case in configurations()]


@test(CASES, mark="slow")
async def pagination_visits_every_order_once(case: tuple[str, str]) -> None:
    """Follow returned cursors rather than synthesizing continuation values."""
    recorded = await load_fixture(observations())
    assert_eq(recorded[case]["walk"], [102, 101, 103, 104])


@test(CASES, mark="slow")
async def totals_use_historical_line_prices(case: tuple[str, str]) -> None:
    """Current product prices deliberately disagree with every historical price."""
    recorded = await load_fixture(observations())
    assert_eq(
        [
            order["total_cents"]
            for order in recorded[case]["operations"]["all"]["result"]["orders"]
        ],
        [125, 880, 0, 150],
    )


@test(CASES, mark="slow")
async def shared_products_do_not_collapse_lines(case: tuple[str, str]) -> None:
    """Two lines sharing a product remain distinct historical purchases."""
    recorded = await load_fixture(observations())
    assert_eq(
        [
            item["id"]
            for item in recorded[case]["operations"]["detail"]["result"]["items"]
        ],
        [1001, 1002, 1003],
    )


@test(CASES, mark="slow")
async def product_names_survive_resource_closure(case: tuple[str, str]) -> None:
    """Serialization traverses product values after all database resources close."""
    recorded = await load_fixture(observations())
    assert_eq(
        [
            item["product_name"]
            for item in recorded[case]["operations"]["detail"]["result"]["items"]
        ],
        ["Widget", "Gadget", "Widget"],
    )


@test(CASES, mark="slow")
async def customer_filter_excludes_other_orders(case: tuple[str, str]) -> None:
    """Customer 2 has only order 201 despite its higher sort key."""
    recorded = await load_fixture(observations())
    assert_eq(
        [
            order["id"]
            for order in recorded[case]["operations"]["other"]["result"]["orders"]
        ],
        [201],
    )


@test(CASES, mark="slow")
async def customer_name_is_loaded(case: tuple[str, str]) -> None:
    """Customer projection or relationship loading must preserve the right owner."""
    recorded = await load_fixture(observations())
    assert_eq(
        recorded[case]["operations"]["other"]["result"]["orders"][0]["customer_name"],
        "Ben",
    )


@test(CASES, mark="slow")
async def empty_order_has_no_items(case: tuple[str, str]) -> None:
    """An order with no lines remains a real detail object."""
    recorded = await load_fixture(observations())
    assert_eq(recorded[case]["operations"]["empty"]["result"]["items"], ())


@test(CASES, mark="slow")
async def empty_order_total_is_zero(case: tuple[str, str]) -> None:
    """Empty totals are zero, not null or an absent order."""
    recorded = await load_fixture(observations())
    assert_eq(recorded[case]["operations"]["empty"]["result"]["total_cents"], 0)


@test(CASES, mark="slow")
async def missing_order_returns_none(case: tuple[str, str]) -> None:
    """Absence is distinct from an empty collection."""
    recorded = await load_fixture(observations())
    assert_is_none(recorded[case]["operations"]["missing"]["result"])


@test(CASES, mark="slow")
async def first_cursor_names_last_returned_order(case: tuple[str, str]) -> None:
    """Do not use the lookahead order as the exclusive continuation boundary."""
    recorded = await load_fixture(observations())
    assert_eq(recorded[case]["operations"]["first"]["result"]["next_cursor"], (30, 101))


@test(CASES, mark="slow")
async def terminal_page_has_no_cursor(case: tuple[str, str]) -> None:
    """A full final page is still terminal when the lookahead finds nothing."""
    recorded = await load_fixture(observations())
    assert_is_none(recorded[case]["operations"]["last"]["result"]["next_cursor"])


@test(CASES, mark="slow")
async def empty_customer_returns_empty_page(case: tuple[str, str]) -> None:
    """No parent rows means no phantom order or invalid child IN query."""
    recorded = await load_fixture(observations())
    assert_eq(recorded[case]["operations"]["absent_customer"]["result"]["orders"], ())


@test(CASES, mark="slow")
async def exhausted_cursor_returns_empty_page(case: tuple[str, str]) -> None:
    """The final order is excluded by its own cursor."""
    recorded = await load_fixture(observations())
    assert_eq(recorded[case]["operations"]["exhausted"]["result"]["orders"], ())


@test(CASES, mark="slow")
async def fanout_does_not_truncate_items(case: tuple[str, str]) -> None:
    """All five children remain even when other reads paginate one order at a time."""
    recorded = await load_fixture(observations())
    assert_eq(
        [
            item["id"]
            for item in recorded[case]["operations"]["fanout"]["result"]["items"]
        ],
        [1005, 1006, 1007, 1008, 1009],
    )


@test(CASES, mark="slow")
async def two_order_query_counts_match_observed_plans(case: tuple[str, str]) -> None:
    """Counts describe these plans, not a universal performance requirement."""
    recorded = await load_fixture(observations())
    expected = {"snekql": 2, "selectin": 2, "joined": 1, "per-order": 3}
    assert_eq(recorded[case]["operations"]["first"]["query_count"], expected[case[1]])


@test(CASES, mark="slow")
async def per_order_query_growth_is_visible(case: tuple[str, str]) -> None:
    """Four orders cost five SELECTs only in the per-order diagnostic."""
    recorded = await load_fixture(observations())
    expected = {"snekql": 2, "selectin": 2, "joined": 1, "per-order": 5}
    assert_eq(recorded[case]["operations"]["all"]["query_count"], expected[case[1]])


@test(CASES, mark="slow")
async def absent_order_needs_no_child_query(case: tuple[str, str]) -> None:
    """The missing-parent path executes one SELECT in every plan."""
    recorded = await load_fixture(observations())
    assert_eq(recorded[case]["operations"]["missing"]["query_count"], 1)


@test(CASES, mark="slow")
async def paginated_orders_keep_complete_totals(case: tuple[str, str]) -> None:
    """LIMIT on the parent page must not truncate the second order's children."""
    recorded = await load_fixture(observations())
    assert_eq(
        [
            order["total_cents"]
            for order in recorded[case]["operations"]["first"]["result"]["orders"]
        ],
        [125, 880],
    )
