"""Keep transaction completion, request success, and contention distinct."""

from typing import Any

from sqlalchemy.exc import DBAPIError


class ObservationError(Exception):
    """The experiment received a result outside its single-row contract."""


def assess(callers: list[dict[str, Any]], final: dict[str, int]) -> str:
    """Count successful requests, not UPDATE executions or attempted retries."""
    successes = sum(caller["outcome"] == "committed" for caller in callers)
    if final["quantity"] != 10 - successes:
        return "lost_update"
    return "two_applied" if successes == len(callers) else "conflict_exposed"


def contention(error: Exception, stage: str) -> dict[str, Any]:
    """Never retry unknown errors or an ambiguous commit failure."""
    driver = error.orig if isinstance(error, DBAPIError) else error.__cause__
    code = getattr(driver, "sqlite_errorcode", None)
    if code is None:
        code = getattr(driver, "args", (None,))[0]
    if stage != "execute" or code not in (5, 517, 1020, 1205):
        raise error
    return {
        "outcome": "contention",
        "stage": stage,
        "code": code,
        "error_type": type(error).__name__,
        "driver_type": type(driver).__name__,
        "message": str(error),
    }
