"""Application outcomes and executed-query evidence through approved boundaries."""

import asyncio
from collections.abc import Awaitable
from dataclasses import asdict
from importlib.metadata import version
from json import dumps
from pathlib import Path
from platform import python_version
from typing import Any

from research.loading.resources import application
from research.loading.views import LoadingStudyError, OrderView, Page


def configurations() -> list[tuple[str, str]]:
    """Representative read plans plus the explicitly labeled per-order diagnostic."""
    return [
        (backend, strategy)
        for backend in ("sqlite", "mariadb")
        for strategy in ("snekql", "selectin", "joined", "per-order")
    ]


async def observe(backend: str, strategy: str) -> dict[str, Any]:
    """Serialize returned values after all owning database resources have closed."""
    operations: dict[str, Any] = {}
    returned: dict[str, Page | OrderView | None] = {}
    async with asyncio.timeout(30), application(backend, strategy) as study:

        async def record(
            name: str, operation: Awaitable[Page | OrderView | None]
        ) -> None:
            study.statements.clear()
            returned[name] = await operation
            operations[name] = {
                "query_count": len(study.statements),
                "sql": [asdict(statement) for statement in study.statements],
            }

        for name, customer, cursor, limit in (
            ("first", 1, None, 2),
            ("one", 1, None, 1),
            ("all", 1, None, 10),
            ("tied", 1, (30, 102), 2),
            ("last", 1, (30, 101), 2),
            ("other", 2, None, 2),
            ("absent_customer", 999, None, 2),
            ("exhausted", 1, (10, 104), 2),
        ):
            await record(name, study.app.list_orders(customer, cursor, limit))
        for name, order_id in (
            ("detail", 101),
            ("empty", 103),
            ("fanout", 104),
            ("missing", 999),
        ):
            await record(name, study.app.get_order(order_id))
        cursor = None
        walk: list[int] = []
        for index in range(5):
            study.statements.clear()
            page = await study.app.list_orders(1, cursor, 1)
            name = f"walk_{index}"
            returned[name] = page
            operations[name] = {
                "query_count": len(study.statements),
                "sql": [asdict(statement) for statement in study.statements],
            }
            walk.extend(order.id for order in page.orders)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        else:
            message = "pagination failed to terminate for four specified orders"
            raise LoadingStudyError(message)
    # Serialization happens after the engine, sessions, transactions, and server close.
    for name, result in returned.items():
        operations[name]["result"] = None if result is None else asdict(result)
    return {
        "backend": backend,
        "strategy": strategy,
        "controls": study.controls,
        "ddl": study.ddl,
        "operations": operations,
        "walk": walk,
        "serialized_after_close": True,
    }


async def main() -> None:
    """Retain reproduction evidence next to the research application."""
    evidence: dict[str, Any] = {
        "python": python_version(),
        "versions": {
            name: version(name)
            for name in (
                "snekql",
                "SQLAlchemy",
                "greenlet",
                "pydantic",
                "aiosqlite",
                "aiomysql",
                "PyMySQL",
            )
        },
        "runs": {
            f"{backend}/{strategy}": await observe(backend, strategy)
            for backend, strategy in configurations()
        },
    }
    directory = Path(__file__).parent
    await asyncio.to_thread(
        (directory / "results.json").write_text, dumps(evidence, indent=2) + "\n"
    )
    for name, run in evidence["runs"].items():
        ddl = "\n\n".join(
            "\n".join(line.rstrip() for line in sql.strip().rstrip(";").splitlines())
            + ";"
            for sql in run["ddl"].values()
        )
        await asyncio.to_thread(
            (directory / f"{name.replace('/', '-')}.sql").write_text, ddl + "\n"
        )


if __name__ == "__main__":
    asyncio.run(main())
