"""Erased keyword callers distinguish missing, NULL, real values, and sentinels."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from snekql import sqlite
from snektest import Param, assert_eq, test

from scratchpad.paired_situations import body, dual, nested


@dataclass(frozen=True)
class DefaultCase:
    field: str
    value: object
    nullable: bool
    default: object


CASES = (
    DefaultCase("timezone", "Europe/Paris", False, "error"),
    DefaultCase("nickname", "Ada", True, "error"),
    DefaultCase("enabled", False, False, True),
    DefaultCase("note", "hello", True, None),
    DefaultCase("digest_hour", 18, False, "omitted"),
    DefaultCase("locale", "en", True, "omitted"),
    DefaultCase("created_at", datetime(2026, 1, 1, tzinfo=UTC), False, "omitted"),
)


@test(
    [Param(value=case, name=case.field) for case in CASES],
    [
        Param(value=operation, name=operation)
        for operation in ("missing", "null", "value", "omitted")
    ],
    [Param(value=approach, name=approach) for approach in ("nested", "body", "dual")],
    [Param(value=contract, name=contract) for contract in ("input", "complete")],
    mark="fast",
)
def erased_default_contract(
    case: DefaultCase, operation: str, approach: str, contract: str
) -> None:
    # This seam deliberately erases keyword checking to exercise runtime guards.
    constructors: dict[str, Any] = {
        "dual-input": dual.Settings,
        "dual-complete": dual.SettingsRow,
        "nested-input": nested.Settings.Pending,
        "nested-complete": nested.Settings,
        "body-input": body.Settings,
        "body-complete": body.Settings[sqlite.Fetched],
    }
    constructor = constructors[f"{approach}-{contract}"]
    sentinel = body.OMITTED if approach == "body" else nested.OMITTED
    arguments: dict[str, object] = {item.field: item.value for item in CASES}
    arguments["user_id"] = 1
    if operation == "missing":
        del arguments[case.field]
        expected = (
            "error"
            if contract == "complete"
            and (
                approach == "nested"
                or (approach == "dual" and case.default == "omitted")
            )
            else case.default
        )
    elif operation == "null":
        arguments[case.field] = None
        expected = None if case.nullable else "error"
    elif operation == "omitted":
        arguments[case.field] = sentinel
        expected = (
            "omitted"
            if case.default == "omitted"
            and not (approach in {"nested", "dual"} and contract == "complete")
            else "error"
        )
    else:
        expected = case.value

    try:
        value = getattr(constructor(**arguments), case.field)
        observed = "omitted" if value is sentinel else value
    except sqlite.ModelValidationError:
        observed = "error"

    assert_eq(observed, expected)
