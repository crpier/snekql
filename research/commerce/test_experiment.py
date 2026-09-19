"""Tests at the experiment's DDL and raw-SQL observation boundaries."""

from snektest import assert_eq, test

from research.commerce.experiment import observe_sqlite


@test(mark="medium")
async def price_order_is_observed_without_python_coercion() -> None:
    """The report must preserve SQLite's lexical money ordering."""
    observation = await observe_sqlite("snekql", "idiomatic")
    assert_eq(observation["probes"]["price_order"]["rows"], [["10"], ["2"]])


@test(mark="medium")
async def sqlite_text_does_not_truncate_raw_timestamp() -> None:
    """A fixed input preserves all six digits in raw TEXT, despite app policy."""
    observation = await observe_sqlite("sqlalchemy", "matched")
    assert_eq(
        observation["probes"]["timestamp_precision"]["rows"],
        [["2026-01-02 03:04:05.123456"]],
    )


@test(mark="medium")
async def negative_price_feedback_names_the_construction_stage() -> None:
    """Application refusal must not be reported as a database constraint."""
    observation = await observe_sqlite("snekql", "idiomatic")
    assert_eq(observation["application"]["price_negative"]["stage"], "construction")


@test(mark="medium")
async def explicit_sqlalchemy_check_rejects_zero_quantity() -> None:
    """The optional database-rule task must execute the emitted CHECK."""
    observation = await observe_sqlite("sqlalchemy", "idiomatic")
    assert_eq(observation["database_rules"]["zero_quantity"]["outcome"], "rejected")


@test(mark="medium")
async def sqlalchemy_sqlite_typed_readback_is_not_storage_precision() -> None:
    """Numeric readback can round a value that raw storage kept at three decimals."""
    observation = await observe_sqlite("sqlalchemy", "idiomatic")
    assert_eq(observation["typed_price_readback"]["typed"], "1.24")


@test(mark="medium")
async def sqlalchemy_sqlite_timezone_flag_does_not_normalize_offset() -> None:
    """Actual bound execution should expose retained wall time and missing offset."""
    observation = await observe_sqlite("sqlalchemy", "idiomatic")
    assert_eq(observation["bound_timestamp"]["typed"], "2026-01-02 08:34:05.123456")
