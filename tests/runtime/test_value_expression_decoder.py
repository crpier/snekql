"""Resolved computed values preserve native domains and SQL NULL contexts."""

from typing import Any

from pydantic import BaseModel, field_validator
from snektest import Param, assert_eq, assert_is, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.errors import ModelValidationError
from tests.query.test_arithmetic import Inventory
from tests.query.test_value_functions import Profile
from tests.runtime.test_arithmetic import provide_sqlite_inventory
from tests.runtime.test_value_functions import (
    MariaProfile,
    provide_mariadb_profiles,
    provide_sqlite_profiles,
)


@test([Param(mode, name=mode) for mode in ("buffered", "streamed")], mark="medium")
async def computed_values_reject_native_domain_drift_even_without_validation(
    mode: str,
) -> None:
    database = await load_fixture(provide_sqlite_inventory())
    invalid = sqlite.select(Inventory.quantity.add(2**63 - 1))
    valid = sqlite.select(Inventory.quantity.add(2))
    async with database.transaction() as tx:

        async def read(query: Any, *, validate: bool) -> list[Any]:
            if mode == "buffered":
                return list(await tx.fetch_all(query, validate=validate))
            async with tx.fetch_chunks(query, size=1, validate=validate) as chunks:
                return [row async for chunk in chunks for row in chunk]

        for validate in (False, True, False):
            with assert_raises(ModelValidationError):
                await read(invalid, validate=validate)
            assert_eq(await read(valid, validate=validate), [5])


class Computed(BaseModel):
    key: int
    text: str
    length: int | None
    amount: float
    missing: str | None

    @field_validator("key")
    @classmethod
    def transform_final(cls, value: int) -> int:
        return value + 100


class Intermediate(Computed):
    @field_validator("text")
    @classmethod
    def reject_intermediate(cls, _value: str) -> str:
        msg = "intermediate application models must not be constructed"
        raise ValueError(msg)


class Role:
    pass


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [Param(mode, name=mode) for mode in ("buffered", "streamed")],
    [Param(shape, name=shape) for shape in ("direct", "derived")],
    mark="medium",
)
async def computed_values_keep_native_domains_and_skip_intermediate_models(
    backend: str, mode: str, shape: str
) -> None:
    api: Any = sqlite if backend == "sqlite" else mariadb
    model: Any = Profile if backend == "sqlite" else MariaProfile
    database = await load_fixture(
        provide_sqlite_profiles() if backend == "sqlite" else provide_mariadb_profiles()
    )
    expressions = {
        "key": model.id.add(2),
        "text": model.nickname.coalesce("MISSING").lower(),
        "length": model.nickname.char_length(),
        "amount": api.case(model.id.eq(2), then=1.5, otherwise=2.5),
        "missing": model.nickname.lower(),
    }
    if shape == "direct":
        query = (
            api.select(model).project(Computed, **expressions).order_by(model.id.asc())
        )
    else:
        labels = {
            name: expression.label(name) for name, expression in expressions.items()
        }
        source = (
            api.select(model).project(Intermediate, **labels).cte(Role, name="computed")
        )
        query = (
            api.select(source)
            .project(
                Computed,
                **{name: source.column(label) for name, label in labels.items()},
            )
            .order_by(source.column(labels["key"]).asc())
        )
    async with database.transaction() as tx:
        for validate in (False, True, False):
            if mode == "buffered":
                rows = await tx.fetch_all(query, validate=validate)
            else:
                async with tx.fetch_chunks(query, size=2, validate=validate) as chunks:
                    rows = [row async for chunk in chunks for row in chunk]
            assert_eq(
                [(r.key, r.text, r.length, r.amount, r.missing) for r in rows],
                [
                    (103, "missing", None, 2.5, None),
                    (104, "ada", 3, 1.5, "ada"),
                    (105, "é界", 2, 2.5, "é界"),
                ],
            )
            assert_is(type(rows[0].key), int)
            assert_is(type(rows[0].amount), float)


class Joined(BaseModel):
    increment: int | None
    fallback: int
    branch: int
    length: int | None


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [Param(mode, name=mode) for mode in ("buffered", "streamed")],
    mark="medium",
)
async def computed_values_distinguish_absent_rows_from_case_and_coalesce_values(
    backend: str, mode: str
) -> None:
    api: Any = sqlite if backend == "sqlite" else mariadb
    model: Any = Profile if backend == "sqlite" else MariaProfile
    database = await load_fixture(
        provide_sqlite_profiles() if backend == "sqlite" else provide_mariadb_profiles()
    )
    peer = api.alias(model, Role, name="peer")
    key, text = peer.column(model.id), peer.column(model.nickname)
    query = (
        api.select(model)
        .left_join(peer, on=model.id.eq_col(key) & key.eq(2))
        .project(
            Joined,
            increment=key.add(1),
            fallback=key.coalesce(8).add(1),
            branch=api.case(key.is_null(), then=4, otherwise=7),
            length=text.char_length(),
        )
        .order_by(model.id.asc())
    )
    async with database.transaction() as tx:
        for validate in (False, True, False):
            if mode == "buffered":
                rows = await tx.fetch_all(query, validate=validate)
            else:
                async with tx.fetch_chunks(query, size=2, validate=validate) as chunks:
                    rows = [row async for chunk in chunks for row in chunk]
            assert_eq(
                [(r.increment, r.fallback, r.branch, r.length) for r in rows],
                [(None, 9, 4, None), (3, 3, 7, 3), (None, 9, 4, None)],
            )
