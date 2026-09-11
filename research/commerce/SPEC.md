# Commerce experiment specification

Follow-up research for #355. No package fixes.

## Tasks

Declare a product price, an alternative integer-cent price, and an order with a
quantity, application-default status, and database-generated creation time.

Desired commerce behavior, evaluated separately from library promises:

- Prices are exact, nonnegative, numerically sortable, and have at most two
  fractional digits. Native decimal target is precision 10, scale 2.
- Integer cents are an alternative representation, not a silent replacement.
- Quantities are positive. Creation time comes from the database when omitted;
  explicit NULL must not invoke a default. An ordinary status update must not
  rewrite creation time.
- A timestamp represents an instant. Record actual representation, fractional
  precision, and session-timezone dependence rather than assuming the Python
  annotation proves those properties.

## Comparisons

Idiomatic examples use snekql CanonicalDecimal/Text on SQLite and Decimal(10,2)
on MariaDB; SQLAlchemy uses Numeric(10,2). snekql uses UtcDatetime with Text or
DateTime and CurrentTimestamp; SQLAlchemy uses DateTime(timezone=True) with
server_default=current_timestamp(). These are chosen examples, not survey data.

A storage-matched SQLAlchemy track uses SQLite Text and the same strftime default,
or MariaDB DATETIME(3) and CURRENT_TIMESTAMP(3). SQLite Text matching deliberately
sacrifices SQLAlchemy's built-in Decimal/datetime conversion. It is only a DDL
comparison, not a claim of application-level equivalence.

A separate database-rule example compares SQLAlchemy CheckConstraint and literal
server_default declarations with the limits of snekql's scaffold. Unsupported
configuration remains explicit; do not patch generated snekql DDL to hide it.

## Boundaries and evidence

Continue the approved emitted-DDL, installed-schema, and raw-SQL boundaries.
Add model construction and public value encoding/bound execution observations
for ergonomics. Keep those distinct from database guarantees. Record rejection
stage and error text; never count an infrastructure error as an expected refusal.

Use fresh data per probe, fixed timestamps for precision checks, SQLite foreign
keys enabled, and strict MariaDB SQL mode. Record versions and timezone. Compare
MariaDB database-clock defaults at UTC and +05:30 using a fixed session clock.

Soft-quality review covers declaration readability, number of explicit decisions,
validation feedback, database knowledge required, and ability to express extra
rules. Ground judgments in the actual declarations and observations. No timed
usability claims, popularity claims, or numeric ergonomic scores.
