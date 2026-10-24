"""Model-free native deployment across defaults, contraction and durable recovery."""

import asyncio
import json
import sys
from typing import ClassVar

from snektest import assert_eq, load_fixture, test

from snekql import mariadb
from snekql.experimental import migrations as m
from tests.experimental.test_migration_targets import provide_package_server


class Initial[S = mariadb.Pending](mariadb.Model[S]):
    """An initial owned table with a generated numeric default."""

    __tablename__ = "default_route"
    __row_type__: ClassVar[mariadb.ReadType[Initial[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    count: mariadb.GenCol[int] = mariadb.Integer(default=mariadb.LiteralDefault(7))


class OptionalNote[S = mariadb.Pending](mariadb.Model[S]):
    """Nullable addition before an explicit reviewed backfill."""

    __tablename__ = "default_route"
    __row_type__: ClassVar[mariadb.ReadType[OptionalNote[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    count: mariadb.GenCol[int] = mariadb.Integer(default=mariadb.LiteralDefault(7))
    note: mariadb.Col[str | None] = mariadb.Text(nullable=True)


class RequiredNote[S = mariadb.Pending](mariadb.Model[S]):
    """The final owned contract retains the numeric default through contraction."""

    __tablename__ = "default_route"
    __row_type__: ClassVar[mariadb.ReadType[RequiredNote[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    count: mariadb.GenCol[int] = mariadb.Integer(default=mariadb.LiteralDefault(7))
    note: mariadb.Col[str] = mariadb.Text()


_CHILD = r"""
import asyncio,json,sys
from pymysql.err import IntegrityError
from snekql import mariadb
from snekql.experimental import migrations as m
async def main():
    payload=json.loads(sys.stdin.read())
    config=mariadb.Config(**payload["config"])
    packages=[m.Package.load(value) for value in payload["packages"]]
    assert "tests.experimental.test_migration_deployment_routes" not in sys.modules
    async with m.connect(config) as target:
        await target.apply(await target.prepare(packages[0],schema_writers_excluded=True))
    async with await mariadb.Database.initialize(config) as db, db.transaction() as tx:
        await tx.execute(mariadb.raw("INSERT INTO default_route(id) VALUES(1)"))
    async with m.connect(config) as target:
        for package in packages[1:3]:
            await target.apply(await target.prepare(package,schema_writers_excluded=True))
    async with await mariadb.Database.initialize(config) as db, db.transaction() as tx:
        await tx.execute(mariadb.raw("INSERT INTO default_route(id,note) VALUES(2,'queued')"))
        before=await tx.fetch_all(mariadb.raw("SELECT id,count,note FROM default_route ORDER BY id"))
    async with m.connect(config) as target:
        plan=await target.prepare(packages[3],schema_writers_excluded=True)
        try:
            await target.apply(plan)
        except IntegrityError:
            pass
        else:
            raise AssertionError("conflicting update unexpectedly completed")
        assert next(p for p in await target.status() if p.revision=="004").phase=="uncertain"
    async with await mariadb.Database.initialize(config) as db, db.transaction() as tx:
        await tx.execute(mariadb.raw("DELETE FROM default_route WHERE id=2"))
    async with m.connect(config) as target:
        recovery=await target.inspect_recovery(plan,schema_writers_excluded=True)
        assert recovery.disposition=="retry_remaining"
        await target.resume(recovery,schema_writers_excluded=True)
        await target.apply(await target.prepare(packages[4],schema_writers_excluded=True))
        phases=[progress.phase for progress in await target.status()]
    async with await mariadb.Database.initialize(config) as db, db.transaction() as tx:
        after=await tx.fetch_all(mariadb.raw("SELECT id,count,note FROM default_route"))
    assert "tests.experimental.test_migration_deployment_routes" not in sys.modules
    print(json.dumps({"before":before,"after":after,"phases":phases}))
asyncio.run(main())
"""


@test(mark="slow")
async def model_free_default_route_recovers_without_replaying_and_relinquishes() -> (
    None
):
    """Frozen packages alone deploy a full native route and preserve the one increment."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [Initial], backend="mariadb"))
    draft = m.generate("002", [OptionalNote], backend="mariadb", previous=first).then(
        m.Checkpoint(name="fill")
    )
    second = m.compile(
        draft.then(
            m.DataChange.from_query(
                mariadb.update(OptionalNote).set(OptionalNote.note.to("filled")).all(),
                checkpoint="fill",
                contract_digest=m.contract_digest(draft, point="fill"),
            )
        )
    )
    third = m.compile(
        m.generate("003", [RequiredNote], backend="mariadb", previous=second)
    )
    draft = m.generate("004", [RequiredNote], backend="mariadb", previous=third).then(
        m.Checkpoint(name="work")
    )
    digest = m.contract_digest(draft, point="work")
    fourth = m.compile(
        draft.then(
            m.DataChange.from_query(
                mariadb.update(RequiredNote)
                .set(RequiredNote.count.to_expr(RequiredNote.count.add(1)))
                .all(),
                checkpoint="work",
                contract_digest=digest,
            ),
            m.DataChange.from_query(
                mariadb.update(RequiredNote).set(RequiredNote.id.to(42)).all(),
                checkpoint="work",
                contract_digest=digest,
            ),
        )
    )
    fifth = m.compile(
        m.generate("005", [], backend="mariadb", previous=fourth).resolve(
            m.RelinquishTable(table_name="default_route")
        )
    )
    payload = json.dumps(
        {
            "config": {
                "database": server.config().database,
                "host": server.config().host,
                "port": server.config().port,
                "user": server.config().user,
                "password": server.config().password,
                "unix_socket": str(server.config().unix_socket),
                "charset": server.config().charset,
            },
            "packages": [p.dump() for p in (first, second, third, fourth, fifth)],
        }
    )
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _CHILD,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await child.communicate(payload.encode())
    finally:
        if child.returncode is None:
            child.kill()
            await child.wait()
    assert_eq(child.returncode, 0, msg=stderr.decode())
    assert_eq(
        json.loads(stdout),
        {
            "before": [
                {"id": 1, "count": 7, "note": "filled"},
                {"id": 2, "count": 7, "note": "queued"},
            ],
            "after": [{"id": 42, "count": 8, "note": "filled"}],
            "phases": ["complete"] * 5,
        },
    )
