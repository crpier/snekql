"""Decimal candidate keys retain their native storage contract in references."""

from decimal import Decimal
from typing import ClassVar

from snektest import Param, assert_eq, assert_in, assert_raises, load_fixture, test

from snekql import mariadb
from tests.helpers import initialized_database, provide_mariadb_server


class Price[S = mariadb.Pending](mariadb.Model[S]):
    """A decimal candidate key with nonzero scale."""

    __row_type__: ClassVar[mariadb.ReadType[Price[mariadb.Row]]]

    amount: Price.Col[Decimal] = mariadb.Decimal(8, 2, unique=True)


class Reference[S = mariadb.Pending](mariadb.Model[S]):
    """Required and nullable eager references to the candidate key."""

    __row_type__: ClassVar[mariadb.ReadType[Reference[mariadb.Row]]]

    amount: Reference.FKCol[Price, Decimal] = mariadb.ForeignKey(Price.amount)
    optional: Reference.FKCol[Price, Decimal | None] = mariadb.ForeignKey(
        Price.amount, default=None
    )


class DeferredReference[S = mariadb.Pending](mariadb.Model[S]):
    """Callable references derive the same storage facts."""

    __row_type__: ClassVar[mariadb.ReadType[DeferredReference[mariadb.Row]]]

    amount: DeferredReference.FKCol[Price, Decimal] = mariadb.ForeignKey(
        lambda: Price.amount, default=Decimal("1.25")
    )
    optional: DeferredReference.FKCol[Price, Decimal | None] = mariadb.ForeignKey(
        lambda: Price.amount, default=None
    )


@test(mark="fast")
def direct_decimal_reference_scaffolds_native_dimensions() -> None:
    """Both eager reference columns use the target's DECIMAL(8,2)."""
    ddl = mariadb.scaffold([Reference])

    assert_in("`amount` DECIMAL(8,2)", ddl)
    assert_in("`optional` DECIMAL(8,2)", ddl)


@test(mark="fast")
def callable_decimal_reference_scaffolds_native_dimensions() -> None:
    """Deferred binding preserves the same precision and scale."""
    ddl = mariadb.scaffold([DeferredReference])

    assert_in("`amount` DECIMAL(8,2)", ddl)
    assert_in("`optional` DECIMAL(8,2)", ddl)


@test(
    [Param(value=None, name="null"), Param(value=Decimal("1.25"), name="value")],
    mark="fast",
)
def direct_decimal_reference_insert_encodes(optional: Decimal | None) -> None:
    """Valid decimal and NULL reference values compile without lost metadata."""
    compiled = mariadb.insert(
        Reference(amount=Decimal("1.25"), optional=optional)
    ).compile()

    assert_eq(compiled.params, (Decimal("1.25"), optional))


@test(mark="fast")
def direct_decimal_reference_comparison_encodes() -> None:
    """Literal comparisons use the derived decimal value encoder."""
    compiled = (
        mariadb.select(Reference.amount)
        .where(Reference.amount.eq(Decimal("1.25")))
        .compile()
    )

    assert_eq(compiled.params, (Decimal("1.25"),))


@test(
    [Param(value="1000000.00", name="precision"), Param(value="1.251", name="scale")],
    mark="fast",
)
def direct_decimal_reference_rejects_out_of_bounds(amount: str) -> None:
    """Copying native dimensions must retain precision and scale validation."""
    with assert_raises(mariadb.ModelValidationError):
        mariadb.insert(Reference(amount=Decimal(amount))).compile()


@test(mark="slow")
async def decimal_candidate_key_reference_round_trips() -> None:
    """MariaDB stores and fetches exact decimal foreign key values."""
    server = await load_fixture(provide_mariadb_server())
    async with await initialized_database(
        server.config(), models=[Price, Reference]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(mariadb.insert(Price(amount=Decimal("1234.56"))))
            await setup.execute(
                mariadb.insert(
                    Reference(amount=Decimal("1234.56"), optional=Decimal("1234.56"))
                )
            )
            await setup.execute(mariadb.insert(Reference(amount=Decimal("1234.56"))))

        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(
                mariadb.select(Reference.amount, Reference.optional)
            )

    assert_eq(
        rows, [(Decimal("1234.56"), Decimal("1234.56")), (Decimal("1234.56"), None)]
    )


@test(mark="fast")
def callable_decimal_reference_insert_encodes() -> None:
    """Callable references encode the same valid decimal parameter."""
    compiled = mariadb.insert(DeferredReference(amount=Decimal("1.25"))).compile()

    assert_eq(compiled.params, (Decimal("1.25"), None))


@test(mark="fast")
def nullable_decimal_reference_comparison_encodes() -> None:
    """Nullable reference comparisons retain nonzero scale metadata."""
    compiled = (
        mariadb.select(Reference.optional)
        .where(Reference.optional.eq(Decimal("1.25")))
        .compile()
    )

    assert_eq(compiled.params, (Decimal("1.25"),))
