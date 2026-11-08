# Explicit precision-loss protection (#599)

Research date: 2026-11-08. Python 3.15.0, Pydantic 2.14.0.

## Summary

Start with existing Pydantic contracts and documented storage recipes. An additional
check on the final serialized write parameter can catch mismatches introduced by
custom serializers, but that is a separate, explicitly scoped policy. None of these
establishes that an arbitrary successful database write preserves its input.

This directory is isolated research, **not new snekql exports or automatic hooks**.
No production/dependency changes, model execution, database calls, backend suites,
DDL execution, schema changes, or migrations were performed. The maintainer approved
comparing public TypeAdapter validation/serialization, final scalar checks and storage
recipes. No public syntax is selected here.

## What was actually run

```sh
uv run snektest research/precision_loss_599
uv run ty check
uv run ruff check .
uv run ruff format --check .
```

The focused suite contains 30 cases. Existing library behavior was probed through
public TypeAdapter calls. The two experimental policies in `policies.py` each had a
failing behavior test before implementation: datetime rejection and final decimal
parameter rejection. No ORM/backend behavior is inferred from those Python tests.

## 1. Decimal to MariaDB DECIMAL(5,2)

An application-owned alias already expresses the useful value restriction:

```python
from decimal import Decimal
from typing import Annotated
from pydantic import Field, TypeAdapter

Amount = Annotated[
    Decimal,
    Field(strict=True, max_digits=5, decimal_places=2),
]

adapter = TypeAdapter(Amount)
adapter.validate_python(Decimal("1.23"))  # accepted unchanged
adapter.validate_python(Decimal("1.2300"))  # accepted: trailing zeros don't lose value
adapter.validate_python(Decimal("1.234"))  # ValidationError
adapter.validate_python(Decimal("1000"))  # ValidationError: too many whole digits
adapter.validate_python(1.23)  # ValidationError: float not accepted
```

The suite also covers 999.99, scaled zero, non-finite values and a low ambient
Decimal context. This is evidence for those examples, not exhaustive equivalence
with all MariaDB DECIMAL semantics or all precisions/Decimal contexts.

Unlike Django's DecimalValidator, these Pydantic constraints disregard harmless
trailing zeros. No custom decimal-fit algorithm is needed for this application
contract. Strictness is intentional: once a float has lost decimal information,
converting it to Decimal cannot recover the intended original value.

### Declaration recipe, before inventing a column helper

Using current snekql declaration syntax, an application can share the precision
constants between the value contract and column declaration:

```python
PRECISION = 5
SCALE = 2
Amount = Annotated[
    Decimal,
    Field(strict=True, max_digits=PRECISION, decimal_places=SCALE),
]

# Inside an application's MariaDB Model:
# amount: db.Col[Amount] = db.Decimal(PRECISION, SCALE)
```

The commented Model fragment is illustrative; it was not executed in the probes.
It preserves the ability to use the same Amount contract in HTTP/application code.
It does **not** automatically prove the live column matches these constants.

A function returning a combined type/column pair would hide this small repetition
but make annotations and field-specifier typing more complicated. No helper was
implemented because the evidence so far does not justify a new abstraction. A
helper would also need to allow intentional differences in brownfield mappings.

## 2. Datetime to an existing millisecond-precision column

A plain strict datetime accepts .123456; it does not describe destination precision.
A small explicit Pydantic AfterValidator suffices for application values:

```python
from datetime import datetime
from typing import Annotated
from pydantic import AfterValidator, Field
from research.precision_loss_599.policies import require_milliseconds

MillisecondDatetime = Annotated[
    datetime,
    Field(strict=True),
    AfterValidator(require_milliseconds),
]
```

The policy checks `microsecond % 1000` and raises, rather than rounding/truncating.
.123000 and .999000 are returned as the original objects; .123456 fails. Strict
Python input rejects text, so this experiment does not silently parse higher
precision text before checking it. It is not a timezone or native-date-range
contract. Parsing raw nanosecond strings would need a separate rule **before**
conversion to Python datetime, which already has only microsecond resolution.

For a new schema, storage retaining Python's full microseconds avoids the need for
this precision restriction. For a legacy DATETIME(3), an explicit restricted
application contract is useful when *all* application values should meet that rule.

Do not silently apply write-fit rules to comparison thresholds. A finer-precision
threshold can be useful even when it cannot itself be stored in the column. If the
application intentionally uses a broader datetime contract, a write-only parameter
check is a different choice from restricting the application type everywhere.

## 3. Exact decimals with SQLite: choose storage, not just a validator

A Pydantic Decimal does not make NUMERIC affinity into exact decimal storage.
The Python probe demonstrates that float conversion loses a long Decimal's digits.
This happens independently of validation of the resulting value.

Two recipes have different uses:

### TEXT for decimal round trips

Pydantic's JSON-mode scalar dump produces decimal text. A long Decimal round-trips
through that text in the probe without losing digits. This means using a genuine
TEXT destination and a binding path that preserves the string, not numeric affinity.

But ordinary Decimal text is **not canonical**: 1.50 and 1.5 serialize differently.
It also does **not** sort numerically: text '10' sorts before '9'. Consequently this
is only a representation experiment, not an endorsement of plain Decimal/TEXT for
SQL equality, unique indexes, ordering, range predicates or aggregation. Collation,
text capacity and actual driver behavior remain separate concerns. Current snekql's
CanonicalDecimal addresses the equality issue; it does not fix numeric ordering.

### Integer minor units for fixed-scale arithmetic

Store cents as an integer when the application uses a fixed two-decimal unit:

```python
MinorUnits = Annotated[
    int,
    Field(strict=True, ge=-(2**63), le=2**63 - 1),
]
# price_cents: db.Col[MinorUnits] = db.Integer()
```

The isolated probe accepts 123 and rejects a float and 2**63. This is an explicit
integer application value, not an implicit Decimal-to-int mapping. It permits useful
numeric database operations, subject to database arithmetic/aggregate limits.
Currency/unit and scale must remain explicit. Any conversion from Decimal must be
exact and reject remainders; avoid float multiplication and int() truncation. No new
conversion helper was needed or prototyped here.

## 4. The serialization gap, and a narrow runtime-check experiment

Both Decimal and datetime probes demonstrate this sequence:

1. Pydantic validates an acceptable logical value.
2. A custom serializer outputs a value with excessive precision.
3. `dump_python(..., warnings="error")` succeeds: its output has the declared
   representation type, but does not necessarily fit the destination.

Revalidating the logical input cannot cover this gap. `require_decimal_5_2` checks
only a final Decimal or decimal-text parameter using existing Pydantic constraints,
and returns the original parameter unchanged. Floats, ints and bools are deliberately
unsupported. This limited accepted representation is **not** a statement that the
database cannot accept other representations. The datetime example similarly checks
a final datetime with the explicit millisecond policy.

These are callable demonstrations, not integrated write hooks. They do not support
arbitrary SQL expressions, triggers, server defaults, server conversions, arbitrary
parameter encodings, bulk operation orchestration or actual-schema discovery. They
also cannot detect a serializer that rounds to a *fitting* value: rejecting that
would require comparing the original logical value with its encoded meaning, under
an explicitly defined equality rule. Decimal numeric equality deliberately ignores
scale; signed zero, original spelling and timezone identity may need other policies.

If integrated later, write-only checks belong after the selected serialization and
before driver binding, and must cover every advertised write path. Further driver
conversion can still lose information. No general storage-validation layer is
proposed.

## Existing snekql protections must not be lost accidentally

Source inspection of current main found:

- `snekql/storage.py`, `_encode_decimal`: rejects non-finite or non-fitting native
  decimals, disregarding trailing coefficient zeros without context-based rounding.
- `_encode_native_temporal`: rejects lower-precision DateTime writes, guarded by
  `write`, so comparison thresholds are not automatically quantized or rejected by
  that precision test.
- ADR 0010 documents decimal-fit rejection, CanonicalDecimal and integer-minor-unit
  guidance. ADR 0022 describes explicit temporal meanings.

These existing protections were inspected, **not newly integration-tested**. The
proposed Pydantic-owned design differs from today's encoding pipeline. Moving or
removing it needs a separate implementation decision and regression coverage; this
research does not authorize weakening existing behavior.

## Recommendation and open questions

1. Recommend existing Pydantic decimal/integer constraints first.
2. Offer the millisecond rejection validator as a documented composition candidate,
   not a newly exported datetime type yet.
3. Prefer full microsecond storage for new datetime columns; require explicit policy
   for lower-precision brownfield columns.
4. Document SQLite's TEXT-versus-integer recipes and their SQL-comparison trade-offs.
5. Keep serialized-parameter checks a separately evaluated, explicit write policy.
   The probes show a real gap, not a complete solution.
6. Do not promise lossless writes, and do not silently normalize values to avoid errors.

Before production design: decide whether final-parameter checks are defaults,
opt-in policies or left to application contracts; how types and storage declarations
share parameters without claiming schema ownership; and how errors, predicates,
SQL expressions, native driver conversions and bulk writes behave. Backend tests
against the actual schema/modes/drivers are required before making storage promises.

## Evidence and sources

- Executed local tests: `test_contracts.py`; experimental policies: `policies.py`.
- [Pydantic Decimal constraints and strictness](https://docs.pydantic.dev/latest/api/standard_library_types/#decimals):
  max_digits/decimal_places exclude trailing zeros; strict Python validation requires
  Decimal. Documentation is unversioned; executable evidence above is 2.14.0.
- [Pydantic datetime types](https://docs.pydantic.dev/latest/api/standard_library_types/#datetimes).
- [SQLite affinity](https://sqlite.org/datatype3.html): NUMERIC can convert numeric
  text into INTEGER/REAL; parenthesized numeric type arguments are ignored.
- [MySQL fractional seconds](https://dev.mysql.com/doc/refman/8.4/en/fractional-seconds.html)
  and [decimal rounding](https://dev.mysql.com/doc/refman/8.4/en/precision-math-rounding.html):
  strict mode/warnings are not universal loss detection. These are documented database
  facts, not native test outcomes from this research.
- Repository [ADR 0010](../../docs/adr/0010-canonicaldecimal-and-canonical-wire-forms.md)
  and [ADR 0022](../../docs/adr/0022-explicit-temporal-meanings.md).
