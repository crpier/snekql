"""Architectural locality tests for public snekql concepts."""

from __future__ import annotations

from snektest import assert_eq, test

from snekql import (
    Database,
    Model,
    SelectModelQuery,
    SnekqlError,
    Text,
    Transaction,
)


@test(mark="fast")
def public_concepts_live_in_domain_modules() -> None:
    """The package facade re-exports concepts from deep domain modules."""

    assert_eq(SnekqlError.__module__, "snekql.errors")
    assert_eq(Text.__module__, "snekql.storage")
    assert_eq(Model.__module__, "snekql.model")
    assert_eq(SelectModelQuery.__module__, "snekql.query")
    assert_eq(Database.__module__, "snekql.runtime")
    assert_eq(Transaction.__module__, "snekql.runtime")
