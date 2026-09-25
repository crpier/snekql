"""Schema verification fails closed when catalog action metadata disappears."""

from typing import Any, ClassVar
from unittest.mock import patch

from aiomysql import Cursor
from snektest import assert_raises, load_fixture, test

from snekql import mariadb
from tests.helpers import migrate_models, provide_mariadb_server


@test(mark="slow")
async def missing_foreign_key_actions_do_not_certify_schema() -> None:
    """Warn mode must not turn incomplete FK metadata into successful verification."""
    server = await load_fixture(provide_mariadb_server())

    class Parent[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Parent[mariadb.Row]]]
        key: mariadb.Col[int] = mariadb.Integer(primary_key=True)

    class Child[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Child[mariadb.Row]]]
        parent: mariadb.FKCol[Parent, int] = mariadb.ForeignKey(Parent.key)

    execute = Cursor.execute

    async def missing_actions(self: Cursor, query: str, args: Any = None) -> Any:
        if "INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS" in query:
            return await execute(self, "SELECT NULL, NULL, NULL, NULL WHERE FALSE")
        return await execute(self, query, args)

    async with await mariadb.Database.initialize(server.config()) as database:
        await migrate_models(database, [Parent, Child])
        with (
            patch.object(Cursor, "execute", missing_actions),
            assert_raises(mariadb.SchemaError),
        ):
            await database.verify([Parent, Child], policy="warn")
