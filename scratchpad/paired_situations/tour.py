"""Run the SQLite stories; MariaDB and negative observations are in the test runner.

The driver erases the choice of approach, not the types inside either review file.
"""

from dataclasses import asdict
from typing import Any

from anyio import run
from snekql import sqlite

from scratchpad.paired_situations import body, dual, nested


async def _visit(
    app: Any, *, nested_contracts: bool, dual_contracts: bool = False
) -> None:
    models = (
        [
            app.UserRow,
            app.CounterRow,
            app.SettingsRow,
            app.PostRow,
            app.CommentRow,
            app.OrderRow,
        ]
        if dual_contracts
        else [app.User, app.Counter, app.Settings, app.Post, app.Comment, app.Order]
    )
    ddl = (
        app.sqlite.scaffold(*models)
        if nested_contracts
        else app.sqlite.scaffold(models)
    )
    async with await app.sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001": ddl})
        async with database.transaction() as transaction:
            user = await app.create_user(transaction, "ada@example.com")
            await app.create_post(transaction, user.user_id, "Notes")
            settings = await app.create_settings(transaction, 1, "UTC", None)
            counter = await app.execute_write(
                transaction, app.sqlite.insert(app.pending_counter()).returning()
            )
            order = await app.create_order(transaction)
        async with database.transaction() as transaction:
            print(
                {
                    "approach": app.__name__.rsplit(".", 1)[-1],
                    "public": asdict(app.public_user(user)),
                    "missing": await app.fetch_user(transaction, app.UserId(999)),
                    "authors": await app.author_emails(transaction),
                    "counter": (counter.counter_id, counter.count),
                    "default": settings.digest_hour,
                    "order": app.order_summary(order),
                    "destination": app.receipt_destination(order),
                }
            )
        async with database.transaction() as transaction:
            patched = await app.patch_user(
                transaction, user.user_id, {"display_name": "Ada"}
            )
            saved = await app.save_settings(transaction, 1, "Europe/Paris")
        print({"name": patched.display_name, "timezone": saved.timezone})
    try:
        print({"mutual_foreign_keys": await app.mutual_foreign_keys()})
    except sqlite.ModelDeclarationError as error:
        print({"mutual_foreign_keys": "unsupported declaration", "error": str(error)})


async def main() -> None:
    await _visit(nested, nested_contracts=True)
    await _visit(body, nested_contracts=False)
    await _visit(dual, nested_contracts=True, dual_contracts=True)


if __name__ == "__main__":
    run(main)
