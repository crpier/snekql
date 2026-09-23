"""Executable model-definition research, separate from production models."""

from collections.abc import AsyncGenerator
from typing import Annotated, assert_type

from aiosqlite import Connection, connect
from annotated_types import Gt
from snektest import assert_eq, assert_raises, fixture, load_fixture, test

from typing_probes.model_definitions.runtime import (
    OMIT,
    Column,
    Field,
    Generated,
    Insert,
    Model,
    ModelError,
    Omitted,
    Record,
    field,
    generated,
    insert_using,
    required,
)


class NewAccount(Record):
    created: Field[int | Omitted] = field(default=OMIT)
    id: Field[int | Omitted] = field(default=OMIT)
    name: Field[str] = field()
    nickname: Field[str | None] = field(default=None)


class Account(NewAccount):
    created: Field[int] = required()
    id: Field[int] = required()
    create = insert_using(NewAccount)


class Single(Model):
    created: Field[int] = field(default=OMIT)
    id: Field[int] = field(default=OMIT)
    name: Field[str] = field()
    nickname: Field[str | None] = field(default=None)


@fixture
async def database() -> AsyncGenerator[Connection]:
    """Use explicit scratch SQL, not a pretend schema compiler."""
    async with connect(":memory:") as connection:
        await connection.execute(
            "CREATE TABLE records (id INTEGER PRIMARY KEY, name TEXT NOT NULL, "
            "nickname TEXT, created INTEGER NOT NULL DEFAULT 777)"
        )
        yield connection


@test(mark="medium")
async def refined_insert_materializes_precise_id() -> None:
    """A checked create call really returns the distinct fetched class."""
    connection = await load_fixture(database())
    command = Account.create(name="Ada")

    account = await command.execute(connection, table="records")

    assert_type(command, Insert[Account])
    assert_type(account, Account)
    assert_type(account.id, int)
    assert_eq(account.id, 1)


@test(mark="medium")
async def refined_insert_honors_explicit_id() -> None:
    """Generated inputs remain explicitly overridable."""
    connection = await load_fixture(database())
    command = Account.create(name="Ada", id=42)

    account = await command.execute(connection, table="records")

    assert_eq(account.id, 42)


@test(mark="medium")
async def second_server_default_materializes() -> None:
    """Refinement is not special-cased to a single primary key."""
    connection = await load_fixture(database())

    account = await Account.create(name="Ada").execute(connection, table="records")

    assert_type(account.created, int)
    assert_eq(account.created, 777)


@test(mark="medium")
async def nullable_default_survives_materialization() -> None:
    """NULL and an omitted generated value remain different concepts."""
    connection = await load_fixture(database())

    account = await Account.create(name="Ada").execute(connection, table="records")

    assert_type(account.nickname, str | None)
    assert_eq(account.nickname, None)


@test(mark="fast")
def pending_model_retains_omitted_marker() -> None:
    """The separate input object remains available when callers need it."""
    pending = NewAccount(name="Ada")

    assert_type(pending.id, int | Omitted)
    assert_eq(pending.id, OMIT)


@test(mark="fast")
def inherited_descriptor_binds_to_read_class() -> None:
    """Sharing fields does not lose the concrete SQL column owner."""
    column = Account.name

    assert_type(column, Column[Account, str])
    assert_eq(column.owner, Account)


@test(mark="fast")
def refined_rows_are_immutable() -> None:
    """Runtime immutability makes narrowed inherited fields safe."""
    account = Account(id=1, created=777, name="Ada")

    with assert_raises(ModelError):
        setattr(account, "id", OMIT)  # noqa: B010 - deliberately bypass static freezing


@test(mark="fast")
def subclass_missing_input_is_caught_before_sql() -> None:
    """An inherited input factory cannot silently supply new required fields."""

    class Regional(Account):
        region: Field[str] = field()

    with assert_raises(ModelError):
        Regional.create(name="Ada")


@test(mark="fast")
def required_subclass_rebinds_its_input() -> None:
    """A new input subclass repairs the inherited factory's fixed signature."""

    class NewRegional(NewAccount):
        region: Field[str] = field()

    class Regional(Account, NewRegional):
        create = insert_using(NewRegional)

    command = Regional.create(name="Ada", region="EU")

    assert_type(command, Insert[Regional])
    assert_eq(command.values["region"], "EU")


@test(mark="medium")
async def nullable_generated_value_can_materialize_null() -> None:
    """Removing Omitted must preserve legitimate SQL NULL in the logical type."""
    connection = await load_fixture(database())
    await connection.execute("ALTER TABLE records ADD COLUMN token TEXT DEFAULT NULL")

    class NewNullable(NewAccount):
        token: Field[str | Omitted | None] = field(default=OMIT)

    class NullableAccount(Account, NewNullable):
        token: Field[str | None] = required()
        create = insert_using(NewNullable)

    account = await NullableAccount.create(name="Ada").execute(
        connection, table="records"
    )

    assert_type(account.token, str | None)
    assert_eq(account.token, None)


@test(mark="fast")
def unrelated_refinement_is_rejected() -> None:
    """ty accepts this override; declaration validation must reject it."""
    with assert_raises(ModelError):

        class WrongAccount(NewAccount):
            id: Field[str] = required()


@test(mark="medium")
async def single_model_create_defers_construction() -> None:
    """A constructor ParamSpec can describe insert inputs without making a row."""
    connection = await load_fixture(database())
    command = Single.create(name="Ada")

    account = await command.execute(connection, table="records")

    assert_type(command, Insert[Single])
    assert_type(account.id, int)
    assert_eq(account.id, 1)


@test(mark="medium")
async def single_model_accepts_explicit_marker_with_generated_descriptor() -> None:
    """A wider constructor setter preserves explicit omission without row state."""
    connection = await load_fixture(database())

    class MarkerModel(Model):
        id: Generated[int] = generated(default=OMIT)
        name: Field[str] = field()

    account = await MarkerModel.create(name="Ada", id=OMIT).execute(
        connection, table="records"
    )

    assert_type(account.id, int)
    assert_eq(account.id, 1)


@test(mark="fast")
def single_model_incomplete_constructor_raises() -> None:
    """The single-class tradeoff is explicit: this passes ty but fails at runtime."""
    with assert_raises(ModelError):
        Single(name="Ada")


@test(mark="fast")
def single_model_complete_constructor_works() -> None:
    """Read-row construction works when all generated values are supplied."""
    account = Single(name="Ada", id=1, created=777)

    assert_eq(account.id, 1)


@test(mark="fast")
def logical_constraints_validate_before_sql() -> None:
    """Simpler declarations must not discard Annotated validation metadata."""

    class PositiveCount(Model):
        count: Field[Annotated[int, Gt(0)]] = field()

    with assert_raises(ModelError):
        PositiveCount.create(count=-1)


@test(mark="fast")
def python_default_factory_runs_per_command() -> None:
    """Client defaults are evaluated for inputs, not lost with deferred rows."""
    calls: list[int] = []

    def next_value() -> int:
        calls.append(1)
        return len(calls)

    class Example(Model):
        value: Field[int] = field(default_factory=next_value)

    first = Example.create()
    second = Example.create()

    assert_eq((first.values["value"], second.values["value"]), (1, 2))
