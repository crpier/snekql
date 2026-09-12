"""Behavior checks through full persistence and independent readback."""

from snektest import assert_eq, test

from research.contracts.experiment import observe_sqlite


@test(mark="medium")
async def sqlalchemy_timestamp_survives_a_new_session() -> None:
    """The custom type must preserve the instant, not the supplied wall time."""
    observation = await observe_sqlite("sqlalchemy")
    assert_eq(
        observation["application"]["offset"]["fetched"]["created_at"],
        "2026-01-02 03:04:05.123000+00:00",
    )


@test(mark="medium")
async def sqlalchemy_rejects_fractional_cents_at_construction() -> None:
    """Validation must run when the ORM attribute is first assigned."""
    observation = await observe_sqlite("sqlalchemy")
    assert_eq(observation["application"]["fractional_cents"]["stage"], "construction")


@test(mark="medium")
async def snekql_reports_the_intentional_literal_default_as_drift() -> None:
    """A working migration is not necessarily accepted by strict model verification."""
    observation = await observe_sqlite("snekql")
    assert_eq(observation["verification"]["strict"], "rejected")


@test(mark="medium")
async def sqlalchemy_database_default_fills_omitted_status() -> None:
    """The ORM declaration must request the database default, not supply Python text."""
    observation = await observe_sqlite("sqlalchemy")
    assert_eq(observation["application"]["defaults"]["before"]["status"], "None")
    assert_eq(observation["application"]["defaults"]["fetched"]["status"], "pending")


@test(mark="medium")
async def sqlalchemy_database_rejects_zero_quantity() -> None:
    """Raw writes must execute the actual emitted CHECK, bypassing all validators."""
    observation = await observe_sqlite("sqlalchemy")
    assert_eq(observation["raw"]["zero_quantity"]["outcome"], "rejected")


@test(mark="medium")
async def snekql_history_verification_does_not_certify_checks() -> None:
    """Out-of-band CHECK removal leaves the migration declaration unchanged."""
    observation = await observe_sqlite("snekql")
    assert_eq(
        observation["drift"]["removed_checks"]["verification"],
        observation["verification"],
    )
    assert_eq(observation["drift"]["removed_checks"]["zero_quantity"], "accepted")


@test(mark="medium")
async def sqlalchemy_create_all_does_not_restore_a_changed_default() -> None:
    """Schema creation is not schema verification or migration."""
    observation = await observe_sqlite("sqlalchemy")
    assert_eq(
        observation["drift"]["changed_default"]["default_readback"]["fetched"][
            "status"
        ],
        "queued",
    )


@test(mark="medium")
async def sqlalchemy_bulk_null_does_not_request_the_timestamp_default() -> None:
    """Bulk dictionary writes skip attribute validators but must preserve explicit None."""
    observation = await observe_sqlite("sqlalchemy")
    assert_eq(observation["bulk"]["null_timestamp"]["outcome"], "rejected")


@test(mark="medium")
async def snekql_input_boundary_rejects_bool_quantity() -> None:
    """The actual-int contract is stronger than snekql's native bool-to-int policy."""
    observation = await observe_sqlite("snekql")
    assert_eq(observation["application"]["bool_quantity"]["outcome"], "rejected")


@test(mark="medium")
async def sqlite_accepts_the_inclusive_upper_bounds() -> None:
    """The declared maxima must remain valid integer values through persistence."""
    observation = await observe_sqlite("sqlalchemy")
    assert_eq(
        observation["application"]["upper_bounds"]["fetched"]["price_cents"],
        "9999999999",
    )
