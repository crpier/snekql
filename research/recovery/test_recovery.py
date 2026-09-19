"""Regression checks through the real runtime observation interface."""

from snektest import assert_eq, test

from research.recovery.experiment import observe_mariadb, observe_sqlite


@test(mark="medium")
async def omitted_note_is_preserved() -> None:
    """A partial update must leave an unspecified nullable field alone."""
    observed = await observe_sqlite("snekql", "native")
    assert_eq(observed["patches"]["note_omitted"]["fresh"]["note"], "keep")


@test(mark="medium")
async def explicit_null_clears_note() -> None:
    """None requests SQL NULL, unlike an omitted patch field."""
    observed = await observe_sqlite("sqlalchemy", "native")
    assert_eq(observed["patches"]["note_null"]["fresh"]["note"], None)


@test(mark="medium")
async def added_policy_rejects_bool_before_assignment() -> None:
    """The explicit patch policy must not accept bool as integer quantity."""
    observed = await observe_sqlite("sqlalchemy", "validated")
    assert_eq(observed["patches"]["quantity_bool"]["stage"], "patch_validation")


@test(mark="medium")
async def escaped_failure_rolls_back_prior_write() -> None:
    """A uniqueness failure leaving the transaction must undo the valid update."""
    observed = await observe_sqlite("snekql", "native")
    assert_eq(observed["lifecycle"]["escaping_error"]["fresh"]["quantity"], 1)


@test(mark="medium")
async def caught_snekql_error_records_reuse_rejection() -> None:
    """A poisoned connection must be reported, not crash the research runner."""
    observed = await observe_sqlite("snekql", "native")
    assert_eq(
        observed["lifecycle"]["caught_error"]["read_after_failure"]["outcome"],
        "rejected",
    )


@test(mark="medium")
async def invalid_stored_quantity_fails_validated_read() -> None:
    """SQLAlchemy needs explicit result validation for a stored domain violation."""
    observed = await observe_sqlite("sqlalchemy", "validated")
    assert_eq(observed["corruption"]["zero_quantity"]["read"]["outcome"], "rejected")


@test(mark="slow")
async def mariadb_malformed_timestamp_is_a_write_rejection() -> None:
    """Driver OperationalError 1292 must not be mistaken for a read failure."""
    observed = await observe_mariadb("snekql", "native")
    assert_eq(
        observed["corruption"]["malformed_timestamp"]["injection"]["stage"],
        "raw_update",
    )


@test(mark="medium")
async def direct_orm_statement_error_does_not_equal_flush_failure() -> None:
    """Caught direct UPDATE failure leaves this SQLite session transaction usable."""
    observed = await observe_sqlite("sqlalchemy", "native")
    assert_eq(observed["statement_error"]["fresh"]["quantity"], 4)
