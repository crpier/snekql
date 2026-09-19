"""Test-first checks through the public research observation interface."""

from snektest import assert_eq, assert_false, test

from research.concurrency.experiment import observe


@test(mark="medium")
async def stale_assignment_exposes_a_lost_update() -> None:
    """Both completed writes cannot be mistaken for two applied decrements."""
    recorded = await observe("sqlite", "snekql")
    assert_eq(recorded["scenarios"]["detached_stale"]["oracle"], "lost_update")


@test(mark="medium")
async def atomic_arithmetic_preserves_both_decrements() -> None:
    """The write must operate on the current database quantity, not the old read."""
    recorded = await observe("sqlite", "snekql")
    assert_eq(recorded["scenarios"]["detached_atomic"]["final"]["quantity"], 8)


@test(mark="medium")
async def revision_predicate_exposes_the_stale_writer() -> None:
    """A zero CAS rowcount is surfaced as an application conflict."""
    recorded = await observe("sqlite", "sqlalchemy")
    assert_eq(
        recorded["scenarios"]["detached_cas"]["callers"][1]["outcome"], "conflict"
    )


@test(mark="medium")
async def overlapping_sqlite_snapshot_exposes_contention() -> None:
    """An old WAL read transaction cannot be upgraded after the other commit."""
    recorded = await observe("sqlite", "snekql")
    assert_eq(
        recorded["scenarios"]["overlap_stale"]["callers"][1]["attempts"][0]["code"], 517
    )


@test(mark="medium")
async def full_transaction_retry_rereads_current_quantity() -> None:
    """The retry must replace the obsolete snapshot rather than resubmit it."""
    recorded = await observe("sqlite", "sqlalchemy")
    assert_eq(
        recorded["scenarios"]["overlap_retry"]["callers"][1]["attempts"][1]["read"][
            "quantity"
        ],
        9,
    )


@test(mark="medium")
async def lock_retry_uses_a_fresh_transaction() -> None:
    """A known held writer forces a busy error before a successful reread/retry."""
    recorded = await observe("sqlite", "snekql")
    assert_eq(recorded["scenarios"]["lock_retry"]["final"]["quantity"], 8)


@test(mark="medium")
async def orm_version_counter_detects_stale_flush() -> None:
    """Mapper versioning must reject the second old object at flush/commit."""
    recorded = await observe("sqlite", "sqlalchemy")
    assert_eq(
        recorded["scenarios"]["orm_versioned"]["callers"][1]["error_type"],
        "StaleDataError",
    )


@test(mark="slow")
async def mariadb_snapshot_conflict_is_recorded() -> None:
    """InnoDB snapshot isolation reports error 1020 for this obsolete read."""
    recorded = await observe("mariadb", "snekql")
    assert_eq(
        recorded["scenarios"]["overlap_stale"]["callers"][1]["attempts"][0]["code"],
        1020,
    )


@test(mark="medium")
async def legacy_sqlite_read_has_no_driver_transaction() -> None:
    """A SQLAlchemy Session transaction need not mean SQLite began a read snapshot."""
    recorded = await observe("sqlite", "sqlalchemy", "legacy")
    assert_false(recorded["controls"][0]["driver_in_transaction"])
