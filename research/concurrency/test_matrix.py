"""Cross-backend outcomes through the observation runner's public interface."""

from collections.abc import AsyncGenerator
from typing import Any

from snektest import Param, assert_eq, fixture, load_fixture, test

from research.concurrency.cases import configurations
from research.concurrency.experiment import observe


@fixture(scope="session")
async def observations() -> AsyncGenerator[dict[str, Any]]:
    """Use real owned databases once per configuration; assertions only read evidence."""
    yield {name: await observe(**options) for name, options in configurations()}


CASES = [Param(value=name, name=name.replace("/", "-")) for name, _ in configurations()]
ORM_CASES = [
    Param(value=name, name=name.replace("/", "-"))
    for name, options in configurations()
    if options["library"] == "sqlalchemy"
]


@test(CASES, mark="slow")
async def both_callers_really_read_ten(case: str) -> None:
    """The schedule must establish stale inputs before either writes."""
    recorded = await load_fixture(observations())
    assert_eq(
        [
            caller["read"]["quantity"]
            for caller in recorded[case]["scenarios"]["detached_stale"]["callers"]
        ],
        [10, 10],
    )


@test(CASES, mark="slow")
async def detached_assignment_loses_one_decrement(case: str) -> None:
    """No-error completion of an unguarded assignment is not conflict detection."""
    recorded = await load_fixture(observations())
    assert_eq(recorded[case]["scenarios"]["detached_stale"]["oracle"], "lost_update")


@test(CASES, mark="slow")
async def atomic_updates_apply_twice(case: str) -> None:
    """Arithmetic executes against the current value in fresh write transactions."""
    recorded = await load_fixture(observations())
    assert_eq(recorded[case]["scenarios"]["detached_atomic"]["final"]["quantity"], 8)


@test(CASES, mark="slow")
async def cas_reports_no_match_for_stale_revision(case: str) -> None:
    """The matched CAS necessarily changes revision, avoiding no-op ambiguity."""
    recorded = await load_fixture(observations())
    assert_eq(
        [
            caller["rowcount"]
            for caller in recorded[case]["scenarios"]["detached_cas"]["callers"]
        ],
        [1, 0],
    )


@test(CASES, mark="slow")
async def retry_reads_the_new_revision(case: str) -> None:
    """The application retry cannot reuse revision 1 from the failed transaction."""
    recorded = await load_fixture(observations())
    assert_eq(
        recorded[case]["scenarios"]["overlap_retry"]["callers"][1]["attempts"][1][
            "read"
        ],
        {"quantity": 9, "revision": 2},
    )


@test(CASES, mark="slow")
async def retry_persists_both_requests(case: str) -> None:
    """A bounded full-transaction retry resolves this controlled stale-read schedule."""
    recorded = await load_fixture(observations())
    assert_eq(recorded[case]["scenarios"]["overlap_retry"]["final"]["quantity"], 8)


@test(CASES, mark="slow")
async def held_lock_causes_a_real_database_error(case: str) -> None:
    """The holder is released only after the database reports busy/lock timeout."""
    recorded = await load_fixture(observations())
    expected = 5 if case.startswith("sqlite/") else 1205
    assert_eq(
        recorded[case]["scenarios"]["lock_retry"]["callers"][1]["attempts"][0]["code"],
        expected,
    )


@test(CASES, mark="slow")
async def lock_retry_preserves_the_first_commit(case: str) -> None:
    """Reread after the held writer commits; do not overwrite it with quantity 9."""
    recorded = await load_fixture(observations())
    assert_eq(recorded[case]["scenarios"]["lock_retry"]["final"]["quantity"], 8)


@test(CASES, mark="slow")
async def noop_rowcount_depends_on_connector_policy(case: str) -> None:
    """MariaDB changed-row counts and SQLAlchemy matched-row counts differ."""
    recorded = await load_fixture(observations())
    expected = 0 if case.startswith("mariadb/snekql") else 1
    assert_eq(recorded[case]["noop_rowcount"], expected)


@test(CASES, mark="slow")
async def overlapping_read_safety_depends_on_transaction_policy(case: str) -> None:
    """Legacy SQLite reads and snapshot-disabled MariaDB permit the stale overwrite."""
    recorded = await load_fixture(observations())
    expected = (
        "lost_update"
        if case.endswith(("legacy", "snapshot-off"))
        else "conflict_exposed"
    )
    assert_eq(recorded[case]["scenarios"]["overlap_stale"]["oracle"], expected)


@test(ORM_CASES, mark="slow")
async def orm_mapper_versioning_rejects_stale_flush(case: str) -> None:
    """Version checking is native ORM policy when explicitly configured."""
    recorded = await load_fixture(observations())
    assert_eq(
        recorded[case]["scenarios"]["orm_versioned"]["callers"][1]["error_type"],
        "StaleDataError",
    )


@test(ORM_CASES, mark="slow")
async def explicit_update_bypasses_mapper_versioning(case: str) -> None:
    """A versioned mapper does not add its predicate to arbitrary UPDATE statements."""
    recorded = await load_fixture(observations())
    assert_eq(
        recorded[case]["scenarios"]["versioned_direct_update"]["final"]["quantity"], 9
    )
