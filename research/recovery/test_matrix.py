"""Cross-engine checks for observed update and recovery contracts."""

from collections.abc import AsyncGenerator
from typing import Any

from snektest import Param, assert_eq, fixture, load_fixture, test

from research.recovery.experiment import observe


@fixture(scope="session")
async def observations() -> AsyncGenerator[dict[str, Any]]:
    """Run each disposable configuration once; tests only inspect its evidence."""
    recorded = {}
    for backend in ("sqlite", "mariadb"):
        for library in ("snekql", "sqlalchemy"):
            for track in ("native", "validated"):
                recorded[f"{backend}/{library}/{track}"] = await observe(
                    backend, library, track
                )
    yield recorded


# Pure collection metadata: no databases start until the fixture is requested.
CASES = [
    Param(value=f"{backend}/{library}/{track}", name=f"{backend}-{library}-{track}")
    for backend in ("sqlite", "mariadb")
    for library in ("snekql", "sqlalchemy")
    for track in ("native", "validated")
]


@test(CASES, mark="slow")
async def committed_update_is_visible_to_fresh_reader(case: str) -> None:
    """The success case must really persist, not merely change a held object."""
    recorded = await load_fixture(observations())
    assert_eq(recorded[case]["lifecycle"]["commit"]["fresh"]["quantity"], 3)


@test(CASES, mark="slow")
async def escaped_error_undoes_prior_write(case: str) -> None:
    """The first successful write belongs to the failed transaction too."""
    recorded = await load_fixture(observations())
    assert_eq(recorded[case]["lifecycle"]["escaping_error"]["fresh"]["quantity"], 1)


@test(CASES, mark="slow")
async def caught_error_does_not_persist_prior_write(case: str) -> None:
    """These direct snekql errors and ORM flush errors both undo the prior write."""
    recorded = await load_fixture(observations())
    assert_eq(recorded[case]["lifecycle"]["caught_error"]["fresh"]["quantity"], 1)


@test(CASES, mark="slow")
async def recovery_can_persist_a_new_write(case: str) -> None:
    """Recover with a new snekql transaction or an explicitly rolled-back session."""
    recorded = await load_fixture(observations())
    assert_eq(
        recorded[case]["lifecycle"]["escaping_error"]["fresh_recovery"]["quantity"], 5
    )


@test(CASES, mark="slow")
async def read_validation_does_not_poison_good_row_read(case: str) -> None:
    """Even when the zero row fails decoding, a valid row remains readable."""
    recorded = await load_fixture(observations())
    assert_eq(
        recorded[case]["corruption"]["zero_quantity"]["same_transaction_good_row"][
            "quantity"
        ],
        1,
    )


@test(CASES, mark="slow")
async def retained_objects_follow_their_library_lifecycle(case: str) -> None:
    """snekql keeps the old snapshot; this non-expiring ORM object holds the update."""
    recorded = await load_fixture(observations())
    expected = 1 if recorded[case]["library"] == "snekql" else 3
    assert_eq(
        recorded[case]["lifecycle"]["commit"]["held_after_exit"]["quantity"], expected
    )


@test(
    [Param(value="sqlite", name="sqlite"), Param(value="mariadb", name="mariadb")],
    mark="slow",
)
async def caught_snekql_error_allows_normal_context_exit(backend: str) -> None:
    """No exit exception does not imply that the prior write committed."""
    recorded = await load_fixture(observations())
    assert_eq(
        recorded[f"{backend}/snekql/native"]["lifecycle"]["caught_error"]["exit"][
            "outcome"
        ],
        "returned_normally",
    )


@test(
    [Param(value="sqlite", name="sqlite"), Param(value="mariadb", name="mariadb")],
    mark="slow",
)
async def orm_rollback_expires_loaded_attributes(backend: str) -> None:
    """expire_on_commit=False does not disable rollback expiration."""
    recorded = await load_fixture(observations())
    assert_eq(
        recorded[f"{backend}/sqlalchemy/native"]["lifecycle"]["escaping_error"][
            "expired_after_exit"
        ],
        ["code", "id", "note", "occurred_at", "quantity"],
    )


@test(
    [Param(value="sqlite", name="sqlite"), Param(value="mariadb", name="mariadb")],
    mark="slow",
)
async def direct_statement_can_recover_without_session_rollback(backend: str) -> None:
    """For these uniqueness errors, direct execute differs from ORM flush."""
    recorded = await load_fixture(observations())
    assert_eq(
        recorded[f"{backend}/sqlalchemy/native"]["statement_error"]["fresh"][
            "quantity"
        ],
        4,
    )


@test(mark="slow")
async def maria_rounding_is_not_reflected_in_nonexpiring_orm_object() -> None:
    """A successful native write can leave held state different from storage."""
    recorded = await load_fixture(observations())
    case = recorded["mariadb/sqlalchemy/native"]["patches"]["quantity_fraction"]
    assert_eq(
        (case["held_after_commit"]["quantity"], case["fresh"]["quantity"]), (1.5, 2)
    )


@test(CASES, mark="slow")
async def quantity_read_policy_is_explicit(case: str) -> None:
    """Native ORM types alone do not reject a stored zero; added policy does."""
    recorded = await load_fixture(observations())
    expected = "accepted" if case.endswith("sqlalchemy/native") else "rejected"
    assert_eq(
        recorded[case]["corruption"]["zero_quantity"]["read"]["outcome"], expected
    )
