"""Application contract checks against owned databases."""

from snektest import assert_eq, test

from research.loading.experiment import observe
from research.loading.resources import application


@test(mark="medium")
async def first_page_contains_distinct_orders() -> None:
    """A three-line order must not consume three pagination slots."""
    async with application("sqlite", "snekql") as study:
        page = await study.app.list_orders(1, None, 2)
    assert_eq([order.id for order in page.orders], [102, 101])


@test(mark="medium")
async def cursor_resolves_tied_sort_keys() -> None:
    """Continuing after 102 must still return 101, which shares its sort key."""
    async with application("sqlite", "snekql") as study:
        page = await study.app.list_orders(1, (30, 102), 2)
    assert_eq([order.id for order in page.orders], [101, 103])


@test(mark="medium")
async def historical_lines_determine_total() -> None:
    """Three lines total 880, including two differently priced copies of Widget."""
    async with application("sqlite", "snekql") as study:
        page = await study.app.list_orders(1, (30, 102), 1)
    assert_eq(page.orders[0].total_cents, 880)


@test(mark="medium")
async def detail_is_usable_after_database_close() -> None:
    """Application detail has no lazy database dependency."""
    async with application("sqlite", "snekql") as study:
        detail = await study.app.get_order(101)
    assert_eq(
        None if detail is None else [item.id for item in detail.items],
        [1001, 1002, 1003],
    )


@test(mark="medium")
async def selectin_eager_loading_returns_complete_orders() -> None:
    """A fresh ORM session loads full collections before returning the page."""
    async with application("sqlite", "selectin") as study:
        page = await study.app.list_orders(1, None, 2)
    assert_eq([order.total_cents for order in page.orders], [125, 880])


@test(mark="medium")
async def orm_detail_returns_all_lines() -> None:
    """Detail assembles historical lines before the session expires its objects."""
    async with application("sqlite", "selectin") as study:
        detail = await study.app.get_order(101)
    assert_eq(None if detail is None else detail.total_cents, 880)


@test(mark="medium")
async def joined_eager_loading_pages_parents() -> None:
    """Joined collection loading must not truncate children at the row limit."""
    async with application("sqlite", "joined") as study:
        page = await study.app.list_orders(1, None, 2)
    assert_eq([len(order.items) for order in page.orders], [1, 3])


@test(mark="slow")
async def mariadb_snekql_reads_historical_total() -> None:
    """The same typed projection application runs against real InnoDB tables."""
    async with application("mariadb", "snekql") as study:
        detail = await study.app.get_order(101)
    assert_eq(None if detail is None else detail.total_cents, 880)


@test(mark="medium")
async def observer_records_batched_selects() -> None:
    """Query evidence counts actual completed application SELECTs, excluding setup."""

    recorded = await observe("sqlite", "snekql")
    assert_eq(recorded["operations"]["first"]["query_count"], 2)


@test(mark="medium")
async def per_order_diagnostic_exposes_extra_selects() -> None:
    """Explicit async relationship access avoids MissingGreenlet but still costs N+1."""

    recorded = await observe("sqlite", "per-order")
    assert_eq(recorded["operations"]["first"]["query_count"], 3)


@test(mark="medium")
async def observer_retains_empty_orders() -> None:
    """An empty detail is an existing order with total zero, not not-found."""
    recorded = await observe("sqlite", "snekql")
    assert_eq(recorded["operations"]["empty"]["result"]["total_cents"], 0)
