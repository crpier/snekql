"""Reporting recipes execute through public raw statements on both backends."""

from snektest import Param, assert_eq, load_fixture, test

from examples import reporting
from snekql.model import BackendFamily
from tests.runtime.test_raw_execution import provide_raw_case


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def rankings_preserve_ties_with_deterministic_positions(
    backend: BackendFamily,
) -> None:
    """Rank skips tied places, dense rank does not, and positions break ties."""
    case = await load_fixture(provide_raw_case(backend))
    statement = case.namespace.raw(
        reporting.RANKING_SQL, validate=reporting.RankedScore
    )

    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(statement)

    assert_eq(
        rows,
        [
            reporting.RankedScore(
                team_id=1, player_id=1, position=1, rank=1, dense_rank=1
            ),
            reporting.RankedScore(
                team_id=1, player_id=2, position=2, rank=1, dense_rank=1
            ),
            reporting.RankedScore(
                team_id=1, player_id=3, position=3, rank=3, dense_rank=2
            ),
            reporting.RankedScore(
                team_id=2, player_id=4, position=1, rank=1, dense_rank=1
            ),
        ],
    )


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def category_walk_returns_bounded_descendants(backend: BackendFamily) -> None:
    """The root is depth zero; the result order is explicit, not traversal order."""
    case = await load_fixture(provide_raw_case(backend))
    statement = case.namespace.raw(
        reporting.CATEGORY_SQLITE
        if backend == "sqlite"
        else reporting.CATEGORY_MARIADB,
        params={"root_id": 1, "max_depth": 2},
        validate=reporting.CategoryVisit,
    )

    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(statement)

    assert_eq(
        rows,
        [
            reporting.CategoryVisit(category_id=1, parent_id=None, depth=0),
            reporting.CategoryVisit(category_id=2, parent_id=1, depth=1),
            reporting.CategoryVisit(category_id=4, parent_id=1, depth=1),
            reporting.CategoryVisit(category_id=3, parent_id=2, depth=2),
        ],
    )


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def combined_results_keep_duplicates(backend: BackendFamily) -> None:
    """UNION ALL retains a row present in both inputs before final pagination."""
    case = await load_fixture(provide_raw_case(backend))
    statement = case.namespace.raw(
        reporting.COMBINED_SQL, validate=reporting.EventIdentity
    )

    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(statement)

    assert_eq(
        rows, [reporting.EventIdentity(event_id=2), reporting.EventIdentity(event_id=2)]
    )


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def combined_results_deduplicate_before_pagination(
    backend: BackendFamily,
) -> None:
    """UNION removes the repeated identifier before final offset and limit."""
    case = await load_fixture(provide_raw_case(backend))
    statement = case.namespace.raw(
        reporting.DISTINCT_SQL, validate=reporting.EventIdentity
    )

    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(statement)

    assert_eq(
        rows, [reporting.EventIdentity(event_id=2), reporting.EventIdentity(event_id=3)]
    )


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def category_walk_depth_zero_keeps_only_root(backend: BackendFamily) -> None:
    """A zero edge budget must not visit even immediate children."""
    case = await load_fixture(provide_raw_case(backend))
    statement = case.namespace.raw(
        reporting.CATEGORY_SQLITE
        if backend == "sqlite"
        else reporting.CATEGORY_MARIADB,
        params={"root_id": 1, "max_depth": 0},
        validate=reporting.CategoryVisit,
    )

    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(statement)

    assert_eq(rows, [reporting.CategoryVisit(category_id=1, parent_id=None, depth=0)])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def category_walk_missing_root_returns_no_visits(backend: BackendFamily) -> None:
    """An empty anchor cannot create a traversal from unrelated categories."""
    case = await load_fixture(provide_raw_case(backend))
    statement = case.namespace.raw(
        reporting.CATEGORY_SQLITE
        if backend == "sqlite"
        else reporting.CATEGORY_MARIADB,
        params={"root_id": 99, "max_depth": 2},
        validate=reporting.CategoryVisit,
    )

    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(statement)

    assert_eq(rows, [])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def category_walk_bounds_cycles_without_deduplicating(
    backend: BackendFamily,
) -> None:
    """A depth predicate bounds revisits but is not cycle detection."""
    case = await load_fixture(provide_raw_case(backend))
    statement = case.namespace.raw(
        reporting.CATEGORY_SQLITE
        if backend == "sqlite"
        else reporting.CATEGORY_MARIADB,
        params={"root_id": 6, "max_depth": 3},
        validate=reporting.CategoryVisit,
    )

    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(statement)

    assert_eq(
        rows,
        [
            reporting.CategoryVisit(category_id=6, parent_id=7, depth=0),
            reporting.CategoryVisit(category_id=7, parent_id=6, depth=1),
            reporting.CategoryVisit(category_id=6, parent_id=7, depth=2),
            reporting.CategoryVisit(category_id=7, parent_id=6, depth=3),
        ],
    )
