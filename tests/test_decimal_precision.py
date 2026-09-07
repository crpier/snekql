"""Exact decimal codecs are independent of application arithmetic contexts."""

from __future__ import annotations

from decimal import Decimal, localcontext

from snektest import Param, assert_eq, test

from snekql.sqlite import CanonicalDecimal, Fetched, Model, Pending, Text


@test(
    [
        Param(value=("1.5000", "1.5"), name="fractional_zeros"),
        Param(value=("-0.000", "0"), name="negative_zero"),
        Param(value=("1E+30", "1000000000000000000000000000000"), name="power"),
        Param(value=("1E-30", "0.000000000000000000000000000001"), name="tiny"),
        Param(
            value=(
                "123456789012345678901234567890123456789",
                "123456789012345678901234567890123456789",
            ),
            name="large_integer",
        ),
        Param(
            value=("-123456789.0123456789", "-123456789.0123456789"), name="negative"
        ),
    ],
    mark="fast",
)
def canonical_decimal_ignores_arithmetic_context(case: tuple[str, str]) -> None:
    """Small precision and exponent bounds must not round or reject exact values."""

    class Price[S = Pending](Model[S, "Price[Fetched]"]):
        """An exact amount with canonical text storage."""

        amount: Price.Col[CanonicalDecimal] = Text()

    source, expected = case
    with localcontext(prec=2, Emax=2, Emin=-2):
        pending = Price(amount=Decimal(source))
        encoded = Price.amount.encode(pending.amount, backend="sqlite")

    assert_eq(encoded, expected)
