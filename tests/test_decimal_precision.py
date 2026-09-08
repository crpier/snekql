"""Decimal normalization and storage checks must never round application values."""

from __future__ import annotations

from decimal import ROUND_UP, Decimal, Inexact, Rounded, localcontext

from snektest import Param, assert_eq, assert_raises, test

from snekql import mariadb, sqlite


@test(mark="fast")
def canonical_decimal_preserves_all_digits() -> None:
    """Model validation preserves decimals longer than the default context precision."""

    class Price[S = sqlite.Pending](sqlite.Model[S, "Price[sqlite.Fetched]"]):
        """A canonical decimal stored as text."""

        amount: Price.Col[sqlite.CanonicalDecimal] = sqlite.Text()

    exact = Decimal("12345678901234567890.1234567890123456789")
    with localcontext(prec=6):
        price = Price(amount=exact)

    assert_eq(price.amount, exact)


@test(mark="fast")
def native_decimal_rejects_nonzero_digits_beyond_scale() -> None:
    """A fractional digit cannot disappear into the ambient rounding precision."""

    class Price[S = mariadb.Pending](mariadb.Model[S, "Price[mariadb.Fetched]"]):
        """A native decimal that accepts at most two fractional digits."""

        amount: Price.Col[Decimal] = mariadb.Decimal(5, 2)

    with localcontext(prec=6), assert_raises(mariadb.ModelValidationError):
        Price.amount.encode(
            Decimal("1.00000000000000000000000000001"), backend="mariadb"
        )


@test(
    [
        Param(value=("1.230000", "1.23"), name="fractional_zeros"),
        Param(value=("1000.000", "1000"), name="integer_zeros"),
        Param(value=("-0E-100", "0"), name="negative_zero"),
        Param(value=("1E+40", "1" + "0" * 40), name="large_integer"),
        Param(value=("1E-40", "0." + "0" * 39 + "1"), name="small_fraction"),
        Param(
            value=("-123456789.123456789000", "-123456789.123456789"),
            name="negative_precision",
        ),
    ],
    mark="fast",
)
def canonical_decimal_wire_form_ignores_context(case: tuple[str, str]) -> None:
    """Canonical text is exact even when rounding or exponent arithmetic would trap."""

    class Price[S = sqlite.Pending](sqlite.Model[S, "Price[sqlite.Fetched]"]):
        """A canonical decimal stored as text."""

        amount: Price.Col[sqlite.CanonicalDecimal] = sqlite.Text()

    with localcontext(prec=6, Emax=9, Emin=-9, rounding=ROUND_UP) as context:
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        encoded = Price.amount.encode(Decimal(case[0]), backend="sqlite")

    assert_eq(encoded, case[1])


@test(
    [
        Param(value="999.990000000000000000000000000000", name="trailing_zeros"),
        Param(value="-999.99", name="negative_limit"),
        Param(value="1E+2", name="positive_exponent"),
        Param(value="-0E-1000", name="zero"),
    ],
    mark="fast",
)
def native_decimal_accepts_exact_values_under_rounding_traps(text: str) -> None:
    """Storage bounds depend on significant digits, not the decimal context."""

    class Price[S = mariadb.Pending](mariadb.Model[S, "Price[mariadb.Fetched]"]):
        """A fixed precision and scale numeric value."""

        amount: Price.Col[Decimal] = mariadb.Decimal(5, 2)

    exact = Decimal(text)
    with localcontext(prec=2, Emax=1, Emin=-1) as context:
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        encoded = Price.amount.encode(exact, backend="mariadb")

    assert_eq(encoded, exact)


@test(
    [
        Param(value="1.00000000000000000000000000001", name="tiny_extra_digit"),
        Param(value="-0.001", name="negative_fraction"),
        Param(value="1000.00", name="integer_overflow"),
        Param(value="1E+10000", name="large_exponent"),
        Param(value="1E-10000", name="small_exponent"),
    ],
    mark="fast",
)
def native_decimal_rejects_exact_out_of_bounds_values(text: str) -> None:
    """Out-of-range values raise the model error without decimal arithmetic errors."""

    class Price[S = mariadb.Pending](mariadb.Model[S, "Price[mariadb.Fetched]"]):
        """A fixed precision and scale numeric value."""

        amount: Price.Col[Decimal] = mariadb.Decimal(5, 2)

    with localcontext(prec=2, Emax=1, Emin=-1) as context:
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        with assert_raises(mariadb.ModelValidationError):
            Price.amount.encode(Decimal(text), backend="mariadb")
