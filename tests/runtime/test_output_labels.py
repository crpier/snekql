"""Labeled expressions retain decoding and strict final result validation."""

from typing import assert_type
from uuid import UUID

from pydantic import BaseModel, field_validator
from snektest import assert_eq, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from tests.query.test_named_projection import Person
from tests.runtime.test_named_codecs import (
    DocumentResult,
    LocalDocument,
    MariaDocument,
    provide_mariadb_documents,
    provide_sqlite_documents,
)
from tests.runtime.test_named_projection import provide_people


@test(mark="medium")
async def sqlite_labeled_columns_keep_logical_codecs() -> None:
    """A token does not replace UUID/JSON decoding with wire-value validation."""
    database = await load_fixture(provide_sqlite_documents())
    query = (
        sqlite.select(LocalDocument)
        .all()
        .project(
            DocumentResult,
            key=LocalDocument.id.label("key"),
            values=LocalDocument.payload.label("values"),
        )
    )

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(query)

    assert_type(row, DocumentResult)
    assert_eq(row, DocumentResult(key=UUID(int=1), values=[2, 3]))


@test(mark="slow")
async def mariadb_labeled_columns_keep_logical_codecs() -> None:
    """Native logical values still decode before the named contract validates."""
    database = await load_fixture(provide_mariadb_documents())
    query = (
        mariadb.select(MariaDocument)
        .all()
        .project(
            DocumentResult,
            key=MariaDocument.id.label("key"),
            values=MariaDocument.payload.label("values"),
        )
    )

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(query)

    assert_type(row, DocumentResult)
    assert_eq(row, DocumentResult(key=UUID(int=1), values=[2, 3]))


@test(mark="medium")
async def labeled_computation_validates_final_values_once() -> None:
    """The result validator runs exactly once after SQL computes the labeled value."""
    database = await load_fixture(provide_people())

    class Computed(BaseModel):
        increment: int

        @field_validator("increment")
        @classmethod
        def subtract_three(cls, value: int) -> int:
            return value - 3

    increment = Person.id.add(4).label("increment")
    query = sqlite.select(Person).all().project(Computed, increment=increment)

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(query)

    assert_type(row, Computed)
    assert_eq(row.increment, 2)


@test(mark="medium")
async def labeled_empty_scalar_materializes_null() -> None:
    """An absent scalar input still produces a row containing SQL NULL."""
    database = await load_fixture(provide_people())

    class ScalarResult(BaseModel):
        absent: int | None

    absent = sqlite.scalar(sqlite.select(Person.id).where(Person.id.eq(-1))).label(
        "absent"
    )
    query = sqlite.select(Person).all().project(ScalarResult, absent=absent)

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(query)

    assert_type(row, ScalarResult)
    assert_eq(row.absent, None)


@test(mark="medium")
async def labeled_aggregates_keep_empty_input_semantics() -> None:
    """COUNT remains zero while SUM is NULL, even without input rows."""
    database = await load_fixture(provide_people())

    class Totals(BaseModel):
        count: int
        total: int | None

    query = (
        sqlite.select(Person)
        .where(Person.id.eq(-1))
        .project(
            Totals,
            count=Person.id.count().label("count"),
            total=Person.id.sum().label("total"),
        )
    )

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(query)

    assert_type(row, Totals)
    assert_eq(row, Totals(count=0, total=None))


@test(mark="slow")
async def labeled_native_json_retains_decoding_and_nulls() -> None:
    """A path with a value and an absent path retain their decoded SQL values."""
    database = await load_fixture(provide_mariadb_documents())

    class Values(BaseModel):
        present: int | None
        missing: int | None

    query = (
        mariadb.select(MariaDocument)
        .all()
        .project(
            Values,
            present=MariaDocument.payload.json_extract_int("$[0]").label("present"),
            missing=MariaDocument.payload.json_extract_int("$[9]").label("missing"),
        )
    )

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(query)

    assert_type(row, Values)
    assert_eq(row, Values(present=2, missing=None))


@test(mark="slow")
async def labeled_native_json_cannot_bypass_final_validation() -> None:
    """Disabling column validation does not disable the named result contract."""
    database = await load_fixture(provide_mariadb_documents())

    class WrongResult(BaseModel):
        value: str

    query = (
        mariadb.select(MariaDocument)
        .all()
        .project(
            WrongResult,
            value=MariaDocument.payload.json_extract_int("$[0]").label("value"),
        )
    )

    async with database.transaction() as transaction:
        with assert_raises(mariadb.ModelValidationError):
            await transaction.fetch_one(query, validate=False)
