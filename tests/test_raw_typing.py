"""Exact backend-owned raw types and consumption-only Transaction overloads."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Literal, assert_type

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from snekql import mariadb, sqlite

if TYPE_CHECKING:

    async def sqlite_results(
        transaction: sqlite.Transaction,
        mode: Literal["mapping", "tuple"],
        typed: sqlite.RawStatement[int],
    ) -> None:
        mapping = sqlite.raw("UPDATE values SET value=1")
        positional = sqlite.raw("SELECT 1", row_mode="tuple")
        dynamic = sqlite.raw("SELECT 1", row_mode=mode)
        assert_type(mapping, sqlite.RawStatement[dict[str, object]])
        assert_type(
            sqlite.raw("", validate=None), sqlite.RawStatement[dict[str, object]]
        )
        assert_type(positional, sqlite.RawStatement[tuple[object, ...]])
        assert_type(
            dynamic, sqlite.RawStatement[dict[str, object] | tuple[object, ...]]
        )
        assert_type(await transaction.fetch_all(mapping), list[dict[str, object]])
        assert_type(await transaction.fetch_one(mapping), dict[str, object])
        assert_type(
            await transaction.fetch_one_or_none(mapping), dict[str, object] | None
        )
        assert_type(
            transaction.fetch_chunks(mapping, size=2),
            sqlite.ChunkStream[dict[str, object]],
        )
        assert_type(await transaction.execute(mapping), int)
        assert_type(await transaction.fetch_all(positional), list[tuple[object, ...]])
        assert_type(await transaction.fetch_one(positional), tuple[object, ...])
        assert_type(
            await transaction.fetch_one_or_none(positional), tuple[object, ...] | None
        )
        assert_type(
            transaction.fetch_chunks(positional, size=2),
            sqlite.ChunkStream[tuple[object, ...]],
        )
        assert_type(await transaction.execute(typed), int)
        assert_type(
            await transaction.fetch_all(dynamic),
            list[dict[str, object] | tuple[object, ...]],
        )
        assert_type(
            await transaction.fetch_one(dynamic), dict[str, object] | tuple[object, ...]
        )
        assert_type(
            await transaction.fetch_one_or_none(dynamic),
            dict[str, object] | tuple[object, ...] | None,
        )
        assert_type(
            transaction.fetch_chunks(dynamic, size=2),
            sqlite.ChunkStream[dict[str, object] | tuple[object, ...]],
        )
        assert_type(await transaction.execute(dynamic), int)

    async def mariadb_results(
        transaction: mariadb.Transaction,
        mode: Literal["mapping", "tuple"],
        typed: mariadb.RawStatement[int],
    ) -> None:
        mapping = mariadb.raw("UPDATE values SET value=1")
        positional = mariadb.raw("SELECT 1", row_mode="tuple")
        dynamic = mariadb.raw("SELECT 1", row_mode=mode)
        assert_type(mapping, mariadb.RawStatement[dict[str, object]])
        assert_type(
            mariadb.raw("", validate=None), mariadb.RawStatement[dict[str, object]]
        )
        assert_type(positional, mariadb.RawStatement[tuple[object, ...]])
        assert_type(
            dynamic, mariadb.RawStatement[dict[str, object] | tuple[object, ...]]
        )
        assert_type(await transaction.fetch_all(mapping), list[dict[str, object]])
        assert_type(await transaction.fetch_one(mapping), dict[str, object])
        assert_type(
            await transaction.fetch_one_or_none(mapping), dict[str, object] | None
        )
        assert_type(
            transaction.fetch_chunks(mapping, size=2),
            mariadb.ChunkStream[dict[str, object]],
        )
        assert_type(await transaction.execute(mapping), int)
        assert_type(await transaction.fetch_all(positional), list[tuple[object, ...]])
        assert_type(await transaction.fetch_one(positional), tuple[object, ...])
        assert_type(
            await transaction.fetch_one_or_none(positional), tuple[object, ...] | None
        )
        assert_type(
            transaction.fetch_chunks(positional, size=2),
            mariadb.ChunkStream[tuple[object, ...]],
        )
        assert_type(await transaction.execute(typed), int)
        assert_type(
            await transaction.fetch_all(dynamic),
            list[dict[str, object] | tuple[object, ...]],
        )
        assert_type(
            await transaction.fetch_one(dynamic), dict[str, object] | tuple[object, ...]
        )
        assert_type(
            await transaction.fetch_one_or_none(dynamic),
            dict[str, object] | tuple[object, ...] | None,
        )
        assert_type(
            transaction.fetch_chunks(dynamic, size=2),
            mariadb.ChunkStream[dict[str, object] | tuple[object, ...]],
        )
        assert_type(await transaction.execute(dynamic), int)

    async def reject_sqlite_misuse(
        transaction: sqlite.Transaction, *, flag: bool, mode: str
    ) -> None:
        statement = sqlite.raw("SELECT 1")
        foreign = mariadb.raw("SELECT 1")
        sqlite.raw("SELECT 1", row_mode=mode)  # ty: ignore[no-matching-overload]
        await transaction.execute(foreign)  # ty: ignore[no-matching-overload]
        await transaction.execute(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.execute(statement, validate=flag)  # ty: ignore[no-matching-overload]
        await transaction.fetch_all(foreign)  # ty: ignore[no-matching-overload]
        await transaction.fetch_all(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.fetch_all(statement, validate=flag)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one(foreign)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one(statement, validate=flag)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one_or_none(foreign)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one_or_none(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one_or_none(statement, validate=flag)  # ty: ignore[no-matching-overload]
        transaction.fetch_chunks(foreign, size=2)  # ty: ignore[no-matching-overload]
        transaction.fetch_chunks(statement, validate=False, size=2)  # ty: ignore[no-matching-overload]
        transaction.fetch_chunks(statement, validate=flag, size=2)  # ty: ignore[no-matching-overload]

    async def reject_mariadb_misuse(
        transaction: mariadb.Transaction, *, flag: bool, mode: str
    ) -> None:
        statement = mariadb.raw("SELECT 1")
        foreign = sqlite.raw("SELECT 1")
        mariadb.raw("SELECT 1", row_mode=mode)  # ty: ignore[no-matching-overload]
        await transaction.execute(foreign)  # ty: ignore[no-matching-overload]
        await transaction.execute(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.execute(statement, validate=flag)  # ty: ignore[no-matching-overload]
        await transaction.fetch_all(foreign)  # ty: ignore[no-matching-overload]
        await transaction.fetch_all(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.fetch_all(statement, validate=flag)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one(foreign)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one(statement, validate=flag)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one_or_none(foreign)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one_or_none(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one_or_none(statement, validate=flag)  # ty: ignore[no-matching-overload]
        transaction.fetch_chunks(foreign, size=2)  # ty: ignore[no-matching-overload]
        transaction.fetch_chunks(statement, validate=False, size=2)  # ty: ignore[no-matching-overload]
        transaction.fetch_chunks(statement, validate=flag, size=2)  # ty: ignore[no-matching-overload]


if TYPE_CHECKING:

    @dataclass
    class Total:
        amount: int

    class ModelTotal(BaseModel):
        amount: int

    class DictTotal(TypedDict):
        amount: int

    async def sqlite_validated(
        transaction: sqlite.Transaction, mode: Literal["mapping", "tuple"]
    ) -> None:
        dataclass_statement = sqlite.raw(
            "UPDATE values SET value=1", validate=Total, row_mode=mode
        )
        assert_type(dataclass_statement, sqlite.RawStatement[Total])
        assert_type(await transaction.fetch_all(dataclass_statement), list[Total])
        assert_type(await transaction.fetch_one(dataclass_statement), Total)
        assert_type(
            await transaction.fetch_one_or_none(dataclass_statement), Total | None
        )
        assert_type(await transaction.execute(dataclass_statement), int)
        assert_type(
            transaction.fetch_chunks(dataclass_statement, size=2),
            sqlite.ChunkStream[Total],
        )
        model = sqlite.raw(
            "UPDATE values SET value=1", validate=ModelTotal, row_mode=mode
        )
        assert_type(model, sqlite.RawStatement[ModelTotal])
        assert_type(await transaction.fetch_all(model), list[ModelTotal])
        assert_type(await transaction.fetch_one(model), ModelTotal)
        assert_type(await transaction.fetch_one_or_none(model), ModelTotal | None)
        assert_type(await transaction.execute(model), int)
        assert_type(
            transaction.fetch_chunks(model, size=2), sqlite.ChunkStream[ModelTotal]
        )
        typed_dict = sqlite.raw(
            "UPDATE values SET value=1", validate=DictTotal, row_mode=mode
        )
        assert_type(typed_dict, sqlite.RawStatement[DictTotal])
        assert_type(await transaction.fetch_all(typed_dict), list[DictTotal])
        assert_type(await transaction.fetch_one(typed_dict), DictTotal)
        assert_type(await transaction.fetch_one_or_none(typed_dict), DictTotal | None)
        assert_type(await transaction.execute(typed_dict), int)
        assert_type(
            transaction.fetch_chunks(typed_dict, size=2), sqlite.ChunkStream[DictTotal]
        )
        tuple_row = sqlite.raw(
            "UPDATE values SET value=1",
            validate=tuple[int, str | None],
            row_mode=mode,
        )
        assert_type(tuple_row, sqlite.RawStatement[tuple[int, str | None]])
        assert_type(
            await transaction.fetch_all(tuple_row), list[tuple[int, str | None]]
        )
        assert_type(await transaction.fetch_one(tuple_row), tuple[int, str | None])
        assert_type(
            await transaction.fetch_one_or_none(tuple_row),
            tuple[int, str | None] | None,
        )
        assert_type(await transaction.execute(tuple_row), int)
        assert_type(
            transaction.fetch_chunks(tuple_row, size=2),
            sqlite.ChunkStream[tuple[int, str | None]],
        )
        annotation = sqlite.raw(
            "UPDATE values SET value=1",
            validate=Annotated[tuple[int], Field(min_length=1)],
            row_mode="tuple",
        )
        assert_type(annotation, sqlite.RawStatement[object])
        assert_type(await transaction.fetch_all(annotation), list[object])
        assert_type(await transaction.fetch_one(annotation), object)
        assert_type(await transaction.fetch_one_or_none(annotation), object | None)
        assert_type(await transaction.execute(annotation), int)
        assert_type(
            transaction.fetch_chunks(annotation, size=2), sqlite.ChunkStream[object]
        )

    async def mariadb_validated(
        transaction: mariadb.Transaction, mode: Literal["mapping", "tuple"]
    ) -> None:
        dataclass_statement = mariadb.raw(
            "UPDATE values SET value=1", validate=Total, row_mode=mode
        )
        assert_type(dataclass_statement, mariadb.RawStatement[Total])
        assert_type(await transaction.fetch_all(dataclass_statement), list[Total])
        assert_type(await transaction.fetch_one(dataclass_statement), Total)
        assert_type(
            await transaction.fetch_one_or_none(dataclass_statement), Total | None
        )
        assert_type(await transaction.execute(dataclass_statement), int)
        assert_type(
            transaction.fetch_chunks(dataclass_statement, size=2),
            mariadb.ChunkStream[Total],
        )
        model = mariadb.raw(
            "UPDATE values SET value=1", validate=ModelTotal, row_mode=mode
        )
        assert_type(model, mariadb.RawStatement[ModelTotal])
        assert_type(await transaction.fetch_all(model), list[ModelTotal])
        assert_type(await transaction.fetch_one(model), ModelTotal)
        assert_type(await transaction.fetch_one_or_none(model), ModelTotal | None)
        assert_type(await transaction.execute(model), int)
        assert_type(
            transaction.fetch_chunks(model, size=2), mariadb.ChunkStream[ModelTotal]
        )
        typed_dict = mariadb.raw(
            "UPDATE values SET value=1", validate=DictTotal, row_mode=mode
        )
        assert_type(typed_dict, mariadb.RawStatement[DictTotal])
        assert_type(await transaction.fetch_all(typed_dict), list[DictTotal])
        assert_type(await transaction.fetch_one(typed_dict), DictTotal)
        assert_type(await transaction.fetch_one_or_none(typed_dict), DictTotal | None)
        assert_type(await transaction.execute(typed_dict), int)
        assert_type(
            transaction.fetch_chunks(typed_dict, size=2), mariadb.ChunkStream[DictTotal]
        )
        tuple_row = mariadb.raw(
            "UPDATE values SET value=1",
            validate=tuple[int, str | None],
            row_mode=mode,
        )
        assert_type(tuple_row, mariadb.RawStatement[tuple[int, str | None]])
        assert_type(
            await transaction.fetch_all(tuple_row), list[tuple[int, str | None]]
        )
        assert_type(await transaction.fetch_one(tuple_row), tuple[int, str | None])
        assert_type(
            await transaction.fetch_one_or_none(tuple_row),
            tuple[int, str | None] | None,
        )
        assert_type(await transaction.execute(tuple_row), int)
        assert_type(
            transaction.fetch_chunks(tuple_row, size=2),
            mariadb.ChunkStream[tuple[int, str | None]],
        )
        annotation = mariadb.raw(
            "UPDATE values SET value=1",
            validate=Annotated[tuple[int], Field(min_length=1)],
            row_mode="tuple",
        )
        assert_type(annotation, mariadb.RawStatement[object])
        assert_type(await transaction.fetch_all(annotation), list[object])
        assert_type(await transaction.fetch_one(annotation), object)
        assert_type(await transaction.fetch_one_or_none(annotation), object | None)
        assert_type(await transaction.execute(annotation), int)
        assert_type(
            transaction.fetch_chunks(annotation, size=2), mariadb.ChunkStream[object]
        )

    async def reject_sqlite_validated_misuse(
        transaction: sqlite.Transaction, *, flag: bool, mode: str
    ) -> None:
        statement = sqlite.raw("SELECT 1", validate=Total)
        foreign = mariadb.raw("SELECT 1", validate=Total)
        sqlite.raw("SELECT 1", validate=Total, row_mode=mode)  # ty: ignore[no-matching-overload]
        await transaction.execute(foreign)  # ty: ignore[no-matching-overload]
        await transaction.execute(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.execute(statement, validate=flag)  # ty: ignore[no-matching-overload]
        await transaction.fetch_all(foreign)  # ty: ignore[no-matching-overload]
        await transaction.fetch_all(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.fetch_all(statement, validate=flag)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one(foreign)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one(statement, validate=flag)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one_or_none(foreign)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one_or_none(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one_or_none(statement, validate=flag)  # ty: ignore[no-matching-overload]
        transaction.fetch_chunks(foreign, size=2)  # ty: ignore[no-matching-overload]
        transaction.fetch_chunks(statement, validate=False, size=2)  # ty: ignore[no-matching-overload]
        transaction.fetch_chunks(statement, validate=flag, size=2)  # ty: ignore[no-matching-overload]
        assert_type(sqlite.raw("", validate=Total), sqlite.RawStatement[Total])
        assert_type(
            sqlite.raw("", validate=ModelTotal), sqlite.RawStatement[ModelTotal]
        )
        assert_type(sqlite.raw("", validate=DictTotal), sqlite.RawStatement[DictTotal])
        assert_type(
            sqlite.raw("", validate=tuple[int, str | None]),
            sqlite.RawStatement[tuple[int, str | None]],
        )

    async def reject_mariadb_validated_misuse(
        transaction: mariadb.Transaction, *, flag: bool, mode: str
    ) -> None:
        statement = mariadb.raw("SELECT 1", validate=Total)
        foreign = sqlite.raw("SELECT 1", validate=Total)
        mariadb.raw("SELECT 1", validate=Total, row_mode=mode)  # ty: ignore[no-matching-overload]
        await transaction.execute(foreign)  # ty: ignore[no-matching-overload]
        await transaction.execute(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.execute(statement, validate=flag)  # ty: ignore[no-matching-overload]
        await transaction.fetch_all(foreign)  # ty: ignore[no-matching-overload]
        await transaction.fetch_all(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.fetch_all(statement, validate=flag)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one(foreign)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one(statement, validate=flag)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one_or_none(foreign)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one_or_none(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one_or_none(statement, validate=flag)  # ty: ignore[no-matching-overload]
        transaction.fetch_chunks(foreign, size=2)  # ty: ignore[no-matching-overload]
        transaction.fetch_chunks(statement, validate=False, size=2)  # ty: ignore[no-matching-overload]
        transaction.fetch_chunks(statement, validate=flag, size=2)  # ty: ignore[no-matching-overload]
        assert_type(mariadb.raw("", validate=Total), mariadb.RawStatement[Total])
        assert_type(
            mariadb.raw("", validate=ModelTotal), mariadb.RawStatement[ModelTotal]
        )
        assert_type(
            mariadb.raw("", validate=DictTotal), mariadb.RawStatement[DictTotal]
        )
        assert_type(
            mariadb.raw("", validate=tuple[int, str | None]),
            mariadb.RawStatement[tuple[int, str | None]],
        )
