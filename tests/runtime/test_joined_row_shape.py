"""Joined rows preserve payload positions across physical and named sources."""

from collections.abc import AsyncGenerator
from typing import Any, ClassVar, assert_type

from pydantic import BaseModel
from snektest import Param, assert_eq, fixture, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import provide_mariadb_server


class Anchor[S = sqlite.Pending](sqlite.Model[S]):
    """Non-null row after nullable physical and named payloads."""

    __row_type__: ClassVar[sqlite.ReadType[Anchor[sqlite.Row]]]
    id: Anchor.Col[int] = sqlite.Integer(primary_key=True)


class Payload[S = sqlite.Pending](sqlite.Model[S]):
    """A two-column payload whose entire row can be NULL."""

    __row_type__: ClassVar[sqlite.ReadType[Payload[sqlite.Row]]]
    value: Payload.Col[int | None] = sqlite.Integer()
    note: Payload.Col[str | None] = sqlite.Text()


class NamedPayload(BaseModel):
    """Query-only result with a different field order from its physical source."""

    note: str | None
    value: int | None


class NamedRole:
    """The definition's independent query role."""


class PeerRole:
    """An aliased reference to the definition."""


@fixture
async def joined_rows() -> AsyncGenerator[sqlite.Database]:
    """Seed all-NULL and non-NULL payloads independently of read consumption."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001": sqlite.scaffold([Anchor, Payload])})
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.insert_many(Anchor, [Anchor(id=1), Anchor(id=2)])
            )
            await transaction.execute(
                sqlite.insert_many(
                    Payload,
                    [Payload(value=None, note=None), Payload(value=7, note="seven")],
                )
            )
        yield database


@test(
    [Param("buffered", name="buffered"), Param("streamed", name="streamed")],
    mark="medium",
)
async def mixed_joined_rows_preserve_nullable_payloads(consumption: str) -> None:
    """Presence spans keep physical, CTE alias, and non-null rows aligned."""
    database = await load_fixture(joined_rows())
    definition = (
        sqlite.select(Payload)
        .where(Payload.value.is_null())
        .project(NamedPayload, note=Payload.note, value=Payload.value)
        .cte(NamedRole, name="named_payloads")
    )
    peer = sqlite.alias(definition, PeerRole, name="peer")
    query = (
        sqlite.select(Payload)
        .left_join(peer, on=Payload.value.is_null())
        .join(Anchor, on=Anchor.id.eq(1))
        .order_by(Payload.value.asc())
    )

    async with database.transaction() as transaction:
        if consumption == "streamed":
            async with transaction.fetch_chunks(query, size=1) as stream:
                rows = [row async for chunk in stream for row in chunk]
        else:
            rows = await transaction.fetch_all(query)

    assert_type(
        rows, list[tuple[Payload[sqlite.Row], NamedPayload | None, Anchor[sqlite.Row]]]
    )
    assert_eq(
        [
            (payload.value, payload.note, named, anchor.id)
            for payload, named, anchor in rows
        ],
        [(None, None, NamedPayload(note=None, value=None), 1), (7, "seven", None, 1)],
    )


class NativeAnchor[S = mariadb.Pending](mariadb.Model[S]):
    """Non-null native row after nullable physical and named payloads."""

    __row_type__: ClassVar[mariadb.ReadType[NativeAnchor[mariadb.Row]]]
    id: NativeAnchor.Col[int] = mariadb.Integer(primary_key=True)


class NativePayload[S = mariadb.Pending](mariadb.Model[S]):
    """A two-column native payload whose entire row can be NULL."""

    __row_type__: ClassVar[mariadb.ReadType[NativePayload[mariadb.Row]]]
    value: NativePayload.Col[int | None] = mariadb.Integer()
    note: NativePayload.Col[str | None] = mariadb.Text()


@fixture
async def native_joined_rows() -> AsyncGenerator[mariadb.Database]:
    """Seed native all-NULL and non-NULL payloads before read consumption."""
    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([NativeAnchor, NativePayload])})
        async with database.transaction() as transaction:
            await transaction.execute(
                mariadb.insert_many(
                    NativeAnchor, [NativeAnchor(id=1), NativeAnchor(id=2)]
                )
            )
            await transaction.execute(
                mariadb.insert_many(
                    NativePayload,
                    [
                        NativePayload(value=None, note=None),
                        NativePayload(value=7, note="seven"),
                    ],
                )
            )
        yield database


@test(
    [Param("buffered", name="buffered"), Param("streamed", name="streamed")],
    mark="slow",
)
async def native_mixed_joined_rows_preserve_nullable_payloads(
    consumption: str,
) -> None:
    """Native presence spans keep physical, CTE alias, and non-null rows aligned."""
    database = await load_fixture(native_joined_rows())
    definition = (
        mariadb.select(NativePayload)
        .where(NativePayload.value.is_null())
        .project(NamedPayload, note=NativePayload.note, value=NativePayload.value)
        .cte(NamedRole, name="named_payloads")
    )
    peer = mariadb.alias(definition, PeerRole, name="peer")
    query = (
        mariadb.select(NativePayload)
        .left_join(peer, on=NativePayload.value.is_null())
        .join(NativeAnchor, on=NativeAnchor.id.eq(1))
        .order_by(NativePayload.value.asc())
    )

    async with database.transaction() as transaction:
        if consumption == "streamed":
            async with transaction.fetch_chunks(query, size=1) as stream:
                rows = [row async for chunk in stream for row in chunk]
        else:
            rows = await transaction.fetch_all(query)

    assert_type(
        rows,
        list[
            tuple[
                NativePayload[mariadb.Row],
                NamedPayload | None,
                NativeAnchor[mariadb.Row],
            ]
        ],
    )
    assert_eq(
        [
            (payload.value, payload.note, named, anchor.id)
            for payload, named, anchor in rows
        ],
        [(None, None, NamedPayload(note=None, value=None), 1), (7, "seven", None, 1)],
    )


@test(
    [Param("one", name="one"), Param("optional", name="optional")],
    [Param("matched", name="matched"), Param("absent", name="absent")],
    mark="medium",
)
async def single_joined_row_preserves_nullable_payload(
    consumption: str, match: str
) -> None:
    """Exactly-one and optional consumption use the same mixed-source row shape."""
    database = await load_fixture(joined_rows())
    definition = (
        sqlite.select(Payload)
        .where(Payload.value.is_null())
        .project(NamedPayload, note=Payload.note, value=Payload.value)
        .cte(NamedRole, name="named_payloads")
    )
    query = (
        sqlite.select(Payload)
        .left_join(definition, on=Payload.value.is_null())
        .join(Anchor, on=Anchor.id.eq(1))
        .where(Payload.value.is_null() if match == "matched" else Payload.value.eq(7))
    )

    async with database.transaction() as transaction:
        row = (
            await transaction.fetch_one_or_none(query)
            if consumption == "optional"
            else await transaction.fetch_one(query)
        )

    assert_type(
        row, tuple[Payload[sqlite.Row], NamedPayload | None, Anchor[sqlite.Row]] | None
    )
    assert row is not None
    payload, named, anchor = row
    assert_eq(
        (payload.value, payload.note, named, anchor.id),
        (None, None, NamedPayload(note=None, value=None), 1)
        if match == "matched"
        else (7, "seven", None, 1),
    )


@test(
    [Param("one", name="one"), Param("optional", name="optional")],
    [Param("matched", name="matched"), Param("absent", name="absent")],
    mark="slow",
)
async def native_single_joined_row_preserves_nullable_payload(
    consumption: str, match: str
) -> None:
    """Native exactly-one and optional reads retain mixed-source payload positions."""
    database = await load_fixture(native_joined_rows())
    definition = (
        mariadb.select(NativePayload)
        .where(NativePayload.value.is_null())
        .project(NamedPayload, note=NativePayload.note, value=NativePayload.value)
        .cte(NamedRole, name="named_payloads")
    )
    query = (
        mariadb.select(NativePayload)
        .left_join(definition, on=NativePayload.value.is_null())
        .join(NativeAnchor, on=NativeAnchor.id.eq(1))
        .where(
            NativePayload.value.is_null()
            if match == "matched"
            else NativePayload.value.eq(7)
        )
    )

    async with database.transaction() as transaction:
        row = (
            await transaction.fetch_one_or_none(query)
            if consumption == "optional"
            else await transaction.fetch_one(query)
        )

    assert_type(
        row,
        tuple[
            NativePayload[mariadb.Row], NamedPayload | None, NativeAnchor[mariadb.Row]
        ]
        | None,
    )
    assert row is not None
    payload, named, anchor = row
    assert_eq(
        (payload.value, payload.note, named, anchor.id),
        (None, None, NamedPayload(note=None, value=None), 1)
        if match == "matched"
        else (7, "seven", None, 1),
    )


# Dynamic declarations preserve exact leading underscores instead of Python's
# class-body name mangling; these are legal physical SQL column names. The
# dynamic class declarations deliberately have no statically known owner type.
CollisionPayload: Any = type(
    "CollisionPayload",
    (sqlite.Model,),
    {
        "__module__": __name__,
        "__annotations__": {
            "__row_type__": "ClassVar[sqlite.ReadType[CollisionPayload[sqlite.Row]]]",
            "__snekql_present": "CollisionPayload.Col[int | None]",
            "__SNEKQL_PRESENT_": "CollisionPayload.Col[int | None]",
        },
        "__snekql_present": sqlite.Integer(),
        "__SNEKQL_PRESENT_": sqlite.Integer(),
    },
)
NativeCollisionPayload: Any = type(
    "NativeCollisionPayload",
    (mariadb.Model,),
    {
        "__module__": __name__,
        "__annotations__": {
            "__row_type__": "ClassVar[mariadb.ReadType[NativeCollisionPayload[mariadb.Row]]]",
            "__snekql_present": "NativeCollisionPayload.Col[int | None]",
            "__SNEKQL_PRESENT_": "NativeCollisionPayload.Col[int | None]",
        },
        "__snekql_present": mariadb.Integer(),
        "__SNEKQL_PRESENT_": mariadb.Integer(),
    },
)


@fixture
async def collision_rows() -> AsyncGenerator[sqlite.Database]:
    """Seed legal column names that collide with two private witness candidates."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001": sqlite.scaffold([Anchor, CollisionPayload])})
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.insert_many(Anchor, [Anchor(id=1), Anchor(id=2)])
            )
            await transaction.execute(
                sqlite.raw(
                    'INSERT INTO "collision_payload" VALUES (NULL, NULL), (11, 22)'
                )
            )
        yield database


@test([Param("table", name="table"), Param("alias", name="alias")], mark="medium")
async def hidden_presence_does_not_shadow_physical_payload(source_kind: str) -> None:
    """Case-insensitive marker collisions must preserve visible values and absence."""
    database = await load_fixture(collision_rows())
    source = (
        sqlite.alias(CollisionPayload, PeerRole, name="peer")
        if source_kind == "alias"
        else CollisionPayload
    )
    query = sqlite.select(Anchor).left_join(source, on=Anchor.id.eq(1))

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    observed = [
        (
            anchor.id,
            payload is not None,
            getattr(payload, "__snekql_present", None),
            getattr(payload, "__SNEKQL_PRESENT_", None),
        )
        for anchor, payload in rows
    ]
    assert_eq(
        sorted(observed, key=lambda row: (row[0], row[2] or 0)),
        [(1, True, None, None), (1, True, 11, 22), (2, False, None, None)],
    )


@fixture
async def native_collision_rows() -> AsyncGenerator[mariadb.Database]:
    """Seed native columns that collide with two private witness candidates."""
    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {"001": mariadb.scaffold([NativeAnchor, NativeCollisionPayload])}
        )
        async with database.transaction() as transaction:
            await transaction.execute(
                mariadb.insert_many(
                    NativeAnchor, [NativeAnchor(id=1), NativeAnchor(id=2)]
                )
            )
            await transaction.execute(
                mariadb.raw(
                    "INSERT INTO `native_collision_payload` VALUES (NULL, NULL), (11, 22)"
                )
            )
        yield database


@test([Param("table", name="table"), Param("alias", name="alias")], mark="slow")
async def native_hidden_presence_does_not_shadow_physical_payload(
    source_kind: str,
) -> None:
    """Native marker collisions preserve values and matched all-NULL row identity."""
    database = await load_fixture(native_collision_rows())
    source = (
        mariadb.alias(NativeCollisionPayload, PeerRole, name="peer")
        if source_kind == "alias"
        else NativeCollisionPayload
    )
    query = mariadb.select(NativeAnchor).left_join(source, on=NativeAnchor.id.eq(1))

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    observed = [
        (
            anchor.id,
            payload is not None,
            getattr(payload, "__snekql_present", None),
            getattr(payload, "__SNEKQL_PRESENT_", None),
        )
        for anchor, payload in rows
    ]
    assert_eq(
        sorted(observed, key=lambda row: (row[0], row[2] or 0)),
        [(1, True, None, None), (1, True, 11, 22), (2, False, None, None)],
    )
