"""Whole-model reads retain descriptor and model assignment contracts (#498)."""

from typing import Annotated, Any, ClassVar, cast

from annotated_types import Ge
from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite
from snekql.errors import FrozenModelError, ModelValidationError
from snekql.storage import Attr, StorageBackend
from tests.helpers import initialized_database


class ScaledColumn(Attr[Any, Any, Any, Any, Any]):
    def __set__(self, instance: object, value: Any) -> None:
        super().__set__(instance, value * 2)

    def decode(
        self, value: object, *, backend: StorageBackend, validate: bool = True
    ) -> object:
        decoded = super().decode(value, backend=backend, validate=validate)
        # Whole-model aliases must decode using the original model's columns.
        return decoded if self.owner is SetterReading else 1000


class SetterReading[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[SetterReading[sqlite.Row]]]
    value: SetterReading.Col[int] = cast(
        "Any", ScaledColumn(storage_class="INTEGER", storage_type_name="Integer")
    )


class ReadingRole:
    pass


@test(
    [
        Param(value="buffered", name="buffered"),
        Param(value="streamed", name="streamed"),
    ],
    [Param(value="table", name="table"), Param(value="alias", name="alias")],
    mark="medium",
)
async def whole_model_reads_preserve_assignment_and_immutability(
    mode: str, source_kind: str
) -> None:
    async with (
        await initialized_database(database=":memory:", models=[SetterReading]) as db,
        db.transaction() as tx,
    ):
        await tx.execute(
            sqlite.raw("INSERT INTO setter_reading (value) VALUES (7), (8)")
        )
        alias = sqlite.alias(SetterReading, ReadingRole, name="reading")
        query = (
            sqlite.select(alias).order_by(alias.column(SetterReading.value).asc())
            if source_kind == "alias"
            else sqlite.select(SetterReading).order_by(SetterReading.value.asc())
        )
        if mode == "buffered":
            rows = await tx.fetch_all(query)
        else:
            async with tx.fetch_chunks(query, size=1) as chunks:
                rows = [row async for chunk in chunks for row in chunk]
        assert_eq([row.value for row in rows], [14, 16])
        with assert_raises(FrozenModelError):
            cast("Any", rows[0]).value = 123
        assert_eq(
            await tx.fetch_all(
                sqlite.select(SetterReading.value).order_by(SetterReading.value.asc())
            ),
            [7, 8],
        )


class ValidatedReading[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[ValidatedReading[sqlite.Row]]]
    value: ValidatedReading.Col[Annotated[int, Ge(0)]] = sqlite.Integer()


@test(
    [Param("buffered", name="buffered"), Param("streamed", name="streamed")],
    mark="medium",
)
async def reused_model_query_preserves_each_validation_policy(mode: str) -> None:
    async with (
        await initialized_database(
            database=":memory:", models=[ValidatedReading]
        ) as db,
        db.transaction() as tx,
    ):
        await tx.execute(
            sqlite.raw("INSERT INTO validated_reading (value) VALUES (-5)")
        )
        query = sqlite.select(ValidatedReading)

        async def read(*, validate: bool) -> list[int]:
            if mode == "buffered":
                return [
                    cast("Any", row).value
                    for row in await tx.fetch_all(query, validate=validate)
                ]
            async with tx.fetch_chunks(query, size=1, validate=validate) as chunks:
                return [
                    cast("Any", row).value async for chunk in chunks for row in chunk
                ]

        assert_eq(await read(validate=False), [-5])
        with assert_raises(ModelValidationError):
            await read(validate=True)
        assert_eq(await read(validate=False), [-5])
