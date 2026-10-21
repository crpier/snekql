"""Raw wire-value fidelity through public transactions, not model-codec coverage."""

import warnings
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from snekql import mariadb


def _render(value: object) -> object:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, timedelta):
        return (value.days * 86400 + value.seconds) * 1000000 + value.microseconds
    return value


async def probe(config: mariadb.Config, driver: str, *, stream: bool) -> dict[str, Any]:
    table = f"prototype_values_{driver}"  # Fixed driver names only.
    async with await mariadb.Database.initialize(config) as database:
        async with database.transaction() as setup:
            await setup.execute(
                mariadb.raw(
                    f"CREATE TABLE {table} (id INT PRIMARY KEY, payload BLOB, amount DECIMAL(38,9), "
                    "stamp DATETIME(6), day DATE, duration TIME(6), label VARCHAR(80), "
                    "signed_value BIGINT, unsigned_value BIGINT UNSIGNED, fraction DOUBLE) ENGINE=InnoDB"
                )
            )
        insert = f"INSERT INTO {table} VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"  # noqa: S608
        transaction = database.transaction()
        async with transaction:
            await transaction.execute(
                mariadb.raw(
                    insert,
                    params=(
                        1,
                        bytes(range(256)),
                        Decimal("-12345678901234567890.123456789"),
                        datetime(2024, 2, 29, 23, 59, 58, 123456),  # noqa: DTZ001 - native DATETIME is naive
                        date(2024, 2, 29),
                        timedelta(days=-2, seconds=3, microseconds=456789),
                        "雪 🐍 ' \" \\ \u0000",
                        -(2**63),
                        2**64 - 1,
                        1.25,
                    ),
                )
            )
            await transaction.execute(mariadb.raw(insert, params=(2, *([None] * 9))))
            await transaction.execute(
                mariadb.raw(
                    insert,
                    params=(
                        3,
                        b"",
                        Decimal(0),
                        None,
                        None,
                        None,
                        "",
                        None,
                        None,
                        None,
                    ),
                )
            )
            await transaction.execute(
                mariadb.raw(
                    insert,
                    params=(
                        4,
                        None,
                        None,
                        None,
                        None,
                        "-47:59:56.543211",
                        None,
                        None,
                        None,
                        None,
                    ),
                )
            )
            await transaction.execute(
                mariadb.raw(
                    insert,
                    params=(
                        5,
                        None,
                        None,
                        None,
                        None,
                        timedelta(days=2, seconds=3, microseconds=456789),
                        None,
                        None,
                        None,
                        None,
                    ),
                )
            )
        async with database.transaction() as reader:
            query = mariadb.raw(f"SELECT * FROM {table} ORDER BY id", row_mode="tuple")  # noqa: S608
            chunk_sizes = []
            if stream:
                rows = []
                async with reader.fetch_chunks(query, size=2) as chunks:
                    async for chunk in chunks:
                        chunk_sizes.append(len(chunk))
                        rows.extend(chunk)
            else:
                rows = await reader.fetch_all(query)
            stored = await reader.fetch_one(
                mariadb.raw(
                    f"SELECT CAST(duration AS CHAR) AS value FROM {table} WHERE id = 1"  # noqa: S608
                )
            )
        return {
            "chunk_sizes": chunk_sizes,
            "duration_expected_us": -172796543211,
            "duration_exact": rows[0][5]
            == timedelta(days=-2, seconds=3, microseconds=456789),
            "stored_duration": stored["value"],
            "types": [[type(value).__name__ for value in row] for row in rows],
            "rows": [[_render(value) for value in row] for row in rows],
            "commit_outcome": transaction.commit_outcome,
        }


async def warning_probe(config: mariadb.Config, *, stream: bool) -> dict[str, Any]:
    """Prove a server diagnostic exists without forwarding its sensitive text."""
    canary = "probe-warning-secret-value"
    async with await mariadb.Database.initialize(config) as database:
        async with database.transaction() as transaction:
            statement = mariadb.raw(
                "SELECT CAST(%s AS UNSIGNED) AS value", params=(canary,)
            )
            if stream:
                async with transaction.fetch_chunks(statement, size=1) as chunks:
                    row = (await anext(chunks))[0]
            else:
                row = await transaction.fetch_one(statement)
            # Explicit result inspection is permitted; report only evidence that
            # the warning existed, never its text. This query is not a mock.
            diagnostics = await transaction.fetch_all(mariadb.raw("SHOW WARNINGS"))
        warnings.warn("unrelated-probe-warning", stacklevel=1)
    return {
        "value": row["value"],
        "server_warning_present": any(
            canary in str(item["Message"]) for item in diagnostics
        ),
        "server_warning_codes": [item["Code"] for item in diagnostics],
    }
