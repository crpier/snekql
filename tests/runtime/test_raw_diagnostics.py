"""Raw SQL diagnostics with real connectors and native server warnings."""

import logging
from io import StringIO
from traceback import format_exception
from typing import Literal
from warnings import catch_warnings, simplefilter, warn

from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql.model import BackendFamily
from tests.runtime.test_raw_execution import provide_raw_case


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [Param(value="sql", name="sql"), Param(value="binding", name="binding")],
    [
        Param[Literal["redacted", "values"]](value="redacted", name="redacted"),
        Param[Literal["redacted", "values"]](value="values", name="values"),
    ],
    mark="slow",
)
async def connector_errors_have_safe_rendering(
    backend: BackendFamily,
    stage: str,
    visibility: Literal["redacted", "values"],
) -> None:
    """Native syntax and parameter errors retain classification, not driver text."""

    case = await load_fixture(provide_raw_case(backend, visibility=visibility))
    sql = "SELECT sql_secret FROM absent_secret"
    if stage == "binding":
        sql = "SELECT :key_secret" if backend == "sqlite" else "SELECT %(key_secret)s"
    statement = case.namespace.raw(sql, params={"other_secret": "value_secret"})
    captured = StringIO()
    handler = logging.StreamHandler(captured)
    logger = logging.getLogger("snekql")
    prior_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        with (
            catch_warnings(record=True) as warnings,
            assert_raises(case.namespace.ExecutionError) as raised,
        ):
            simplefilter("always")
            async with case.database.transaction() as transaction:
                await transaction.fetch_all(statement)
        rendered = (
            captured.getvalue()
            + "".join(format_exception(raised.exception))
            + repr(statement)
        )
        rendered += "".join(str(warning.message) for warning in warnings)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prior_level)

    for marker in (
        "sql_secret",
        "absent_secret",
        "key_secret",
        "other_secret",
        "value_secret",
    ):
        assert_eq(marker in rendered, False)


@test(
    [Param(value="buffered", name="buffered"), Param(value="stream", name="stream")],
    mark="slow",
)
async def server_warnings_do_not_forward_sql_values(consumption: str) -> None:
    """Suppress only raw cursor warning forwarding, not unrelated Python warnings."""

    case = await load_fixture(provide_raw_case("mariadb"))
    statement = case.namespace.raw("SELECT CAST('warning_secret' AS UNSIGNED) AS value")

    with catch_warnings(record=True) as warnings:
        simplefilter("always")
        async with case.database.transaction() as transaction:
            if consumption == "stream":
                async with transaction.fetch_chunks(statement, size=1) as stream:
                    await anext(stream)
            else:
                await transaction.fetch_one(statement)
        warn("unrelated_warning", stacklevel=1)

    assert_eq([str(warning.message) for warning in warnings], ["unrelated_warning"])
