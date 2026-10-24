"""Typed descriptor specializations retain public class and value behavior."""

from typing import Any, ClassVar, cast

from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.errors import FrozenModelError
from snekql.storage import FKAttr
from tests.helpers import initialized_database, provide_mariadb_server
from tests.runtime.test_named_codecs import MariaDocument, provide_mariadb_documents


class DoubledAccess(FKAttr[Any, Any, Any, Any, Any, Any, Any, Any, Any]):
    def __get__(self, instance: Any, owner: type[Any]) -> Any:
        value = super().__get__(instance, owner)
        return value if instance is None else value * 2


class Parent[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Parent[sqlite.Row]]]
    id: Parent.Col[int] = sqlite.Integer(primary_key=True)


class Child[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Child[sqlite.Row]]]
    id: Child.Col[int] = sqlite.Integer(primary_key=True)
    parent: Child.FKCol[Parent, int | None] = sqlite.ForeignKey(
        lambda: Parent.id, default=None
    )
    value: Child.Col[int] = cast(
        "Any", DoubledAccess(storage_class="INTEGER", storage_type_name="Integer")
    )


class NativeParent[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[NativeParent[mariadb.Row]]]
    id: NativeParent.Col[int] = mariadb.Integer(primary_key=True)


class NativeChild[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[NativeChild[mariadb.Row]]]
    id: NativeChild.Col[int] = mariadb.Integer(primary_key=True)
    parent: NativeChild.FKCol[NativeParent, int | None] = mariadb.ForeignKey(
        lambda: NativeParent.id, default=None
    )
    value: NativeChild.Col[int] = cast(
        "Any", DoubledAccess(storage_class="INTEGER", storage_type_name="Integer")
    )


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [Param(mode, name=mode) for mode in ("buffered", "streamed")],
    mark="medium",
)
async def class_side_fk_and_custom_value_access_survive_row_lifecycle(
    backend: str, mode: str
) -> None:
    api: Any = sqlite if backend == "sqlite" else mariadb
    parent: Any = Parent if backend == "sqlite" else NativeParent
    child: Any = Child if backend == "sqlite" else NativeChild
    config = (
        sqlite.Config(database=":memory:")
        if backend == "sqlite"
        else (await load_fixture(provide_mariadb_server())).config()
    )
    async with (
        await initialized_database(config, models=[parent, child]) as db,
        db.transaction() as tx,
    ):
        await tx.execute(api.insert(parent(id=7)))
        pending = child(id=1, parent=7, value=3)
        assert_eq(pending.value, 6)
        with assert_raises(FrozenModelError):
            pending.value = 9
        returned = await tx.execute(api.insert(pending).returning())
        assert_eq((returned.parent, returned.value), (7, 12))
        await tx.execute(api.insert(child(id=2, parent=None, value=5)))
        query = (
            api.select(child)
            .left_join(parent, on=child.parent.references(parent.id))
            .order_by(child.id.asc())
        )
        if mode == "buffered":
            rows = await tx.fetch_all(query)
        else:
            async with tx.fetch_chunks(query, size=1) as chunks:
                rows = [row async for chunk in chunks for row in chunk]
        assert_eq(
            [
                (a.id, a.parent, a.value, b.id if b is not None else None)
                for a, b in rows
            ],
            [(1, 7, 12, 7), (2, None, 20, None)],
        )
        with assert_raises(FrozenModelError):
            rows[0][0].value = 0
        assert_eq(
            await tx.fetch_all(api.select(child.value).order_by(child.id.asc())),
            [6, 10],
        )


@test([Param(mode, name=mode) for mode in ("buffered", "streamed")], mark="medium")
async def native_json_keeps_class_operator_and_logical_value_access(mode: str) -> None:
    db = await load_fixture(provide_mariadb_documents())
    async with db.transaction() as tx:
        assert_eq(
            await tx.fetch_all(
                mariadb.select(MariaDocument.payload.json_extract_int("$[0]"))
            ),
            [2],
        )
        query = mariadb.select(MariaDocument)
        if mode == "buffered":
            rows = await tx.fetch_all(query)
        else:
            async with tx.fetch_chunks(query, size=1) as chunks:
                rows = [row async for chunk in chunks for row in chunk]
        assert_eq(rows[0].payload, [2, 3])
        payload = rows[0].payload
        payload.append(4)
        assert_eq(rows[0].payload, [2, 3, 4])
        with assert_raises(FrozenModelError):
            cast("Any", rows[0]).payload = []
        assert_eq(await tx.fetch_all(mariadb.select(MariaDocument.payload)), [[2, 3]])
