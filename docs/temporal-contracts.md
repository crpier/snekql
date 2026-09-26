# Dates and datetimes

Choose a meaning in the annotation, then choose its storage. snekql does not infer
a timezone from the host or change a civil time into an instant.

| Meaning | Logical type | SQLite | MariaDB |
| --- | --- | --- | --- |
| Calendar date | Python `date` | `Text()` | `Date()` |
| Absolute instant | `UtcDatetime` | `Text()` | `DateTime()` |
| Local civil datetime | `LocalDatetime` | `Text()` | `DateTime()` |
| Resolved instant and exact timezone identity | `ZonedDatetime` | `Text()` | `Text()` |

MariaDB also supports canonical temporal text. SQLite still has only four storage
constructors. `Date()` and `DateTime()` are MariaDB-only native declarations.

## Construct values explicitly

All three datetime classes are immutable, shared by the backend namespaces, and
expose the standard-library value through `.datetime`:

```python
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from snekql import sqlite as sql

birthday = date(2000, 2, 29)
occurred_at = sql.UtcDatetime(datetime.now(UTC))
opens_at = sql.LocalDatetime(datetime(2026, 10, 1, 9, 0))
appointment = sql.ZonedDatetime(
    datetime(2026, 10, 1, 9, 0, tzinfo=ZoneInfo("Europe/Paris")),
)

assert occurred_at.datetime.tzinfo is UTC
assert opens_at.datetime.tzinfo is None
```

`UtcDatetime` requires a usable UTC offset and a representable UTC instant. It
normalizes immediately, preserving microseconds. Equality, hashing, and ordering
use the instant, not the original offset.

`LocalDatetime` requires `tzinfo is None` and `fold == 0`. Its civil fields and
microseconds are preserved. It has no implicit UTC interpretation. Equality and
ordering compare the civil fields.

`ZonedDatetime` retains the resolved instant and exact IANA key or fixed offset.
It rejects nonexistent local times, anonymous zone data, and unrepresentable UTC
instants. Different zone aliases remain different identities. Equality and
membership are supported; chronological ordering, ranges, MIN, and MAX are not.
It is not a recurrence or future scheduling policy.

Invalid construction raises `DatetimeError`, or its `ZonedDatetimeError` subclass.
Models translate validation failures to `ModelValidationError`. Model inputs and
query bounds require the actual value classes, not bare datetimes or strings.
Public Pydantic adapters serialize canonical JSON and decode canonical wire text;
strict Python validation requires an instance of the class.

Bare `datetime` and Pydantic `AwareDatetime` temporal columns are rejected.
An explicit custom text codec marked `OrderPreserving` remains an application
extension whose correctness the application must establish. JSON payloads can
still contain ordinary datetimes; they do not acquire temporal-column semantics.

## Declare columns

Inside the corresponding model class:

```python
# SQLite
birthday: sqlite.Col[date] = sqlite.Text()
occurred_at: sqlite.GenCol[sqlite.UtcDatetime] = sqlite.Text(
    default=sqlite.CurrentTimestamp,
)
opens_at: sqlite.Col[sqlite.LocalDatetime] = sqlite.Text()
appointment: sqlite.Col[sqlite.ZonedDatetime] = sqlite.Text()

# MariaDB
birthday: mariadb.Col[date] = mariadb.Date()
occurred_at: mariadb.GenCol[mariadb.UtcDatetime] = mariadb.DateTime(
    default=mariadb.CurrentTimestamp,
)
opens_at: mariadb.Col[mariadb.LocalDatetime] = mariadb.DateTime()
appointment: mariadb.Col[mariadb.ZonedDatetime] = mariadb.Text()
```

Native `DateTime(precision=6)` is the default. Integer precision 0 through 6 is
supported and checked by scaffold/verification. UTC values use timezone-free UTC
fields on the native wire; local values use unchanged civil fields. Native DATE
and DATETIME bindings require years 1000 through 9999. SQLite text does not inherit
that lower bound.

One column has one temporal meaning, optionally nullable; mixed temporal unions
are rejected. UTC and local values are distinct comparison domains, including aliases, CTEs,
aggregates, and scalar subqueries. No implicit conversion makes them comparable.
Logical types do not cause SQL casts between different physical representations.

## Preserve precision

Application values retain all six fractional digits. Canonical text is fixed-width,
including zero-padded years below 1000:

- Date: `2026-10-01`.
- UTC: `2026-10-01T12:00:00.123456Z`.
- Local: `2026-10-01T09:00:00.123456`.
- Zoned: the existing versioned instant-plus-zone representation.

A `DateTime(precision=3)` write accepts `.123000` but rejects `.123456` before driver
I/O. There is no implicit rounding or truncation. Apply any rounding deliberately
in application code.

Predicates retain full precision even against a lower-precision column.
Changing `>= .123456` to `>= .123000` would return different rows:

```python
cutoff = sqlite.UtcDatetime(datetime(2026, 10, 1, 12, 0, 0, 123456, tzinfo=UTC))
query = sqlite.select(Event).where(Event.occurred_at.gte(cutoff))
```

Canonical text readers reject alternate representations rather than hide SQL
comparison differences. Decoder tolerance cannot repair mixed-format queries.

## Database clocks

`CurrentTimestamp` is a database-supplied UTC instant. It requires `UtcDatetime`,
both for generated defaults and explicit UPDATE assignments.

SQLite pads its millisecond clock output to six fractional digits. Padding does
not improve clock resolution or reduce the precision of application writes.
MariaDB native storage uses `CURRENT_TIMESTAMP(p)`; UTC text storage explicitly
formats the same canonical text as application writes. Managed MariaDB sessions
remain UTC. Scaffold, assignment compilation, and verification share this policy.

There is no `CurrentDate` marker. Supply calendar dates in application code or
own a backend-specific default through a migration under the documented
[verification limits](schema-drift.md).

## Upgrade existing applications

This is a breaking contract. Stop old writers and coordinate the schema, data,
and application rollout before resuming comparison queries.

1. Replace bare datetime inputs with the appropriate value class. Access standard
   datetime methods through `.datetime`. Decide UTC versus civil meaning for each
   former bare datetime column; never infer an undocumented historical timezone.
2. Rewrite old millisecond UTC text, its defaults, and external SQL writers to the
   six-digit format. A legacy `.123Z` incorrectly matches `>= .123456Z`; the correct
   `.123000Z` does not. Mixed-version reads are not a compatibility strategy.
3. Widen native `DATETIME(3)` to `DATETIME(6)`, or explicitly retain
   `DateTime(precision=3)` and its exact-write constraint. Widening cannot recover
   digits discarded by older writes.
4. Canonicalize civil text deliberately. Validate range and complete dates before
   moving text into native DATE. Zero dates are not Python dates.
5. Audit indexes, uniqueness, foreign keys, triggers, and external writers.
   Different old representations can collapse to the same canonical value.

The [packaged SQLite example](../snekql/examples/basic.py) demonstrates a table
rebuild without editing its original migrations. It copies known three-digit UTC
text into six-digit text, replaces the clock default, and restores the unique
index. Unexpected source formats fail the NOT NULL constraint rather than lose
information. That example has no referencing tables or triggers; adapt the rebuild
to your actual schema and backup/recovery plan.

For a simple MariaDB column, widening is explicit migration SQL:

```sql
ALTER TABLE event MODIFY occurred_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6);
```

Retain all other column attributes required by your schema. Review MariaDB's DDL
implicit-commit behavior; a migration is not an atomic rollback promise.

Existing canonical `ZonedDatetime` data does not need a rewrite. Its reader now
rejects alternate text spellings too; audit externally written zoned data. snekql performs
no automatic data migration, timezone inference, recurrence handling, or datetime
arithmetic in SQL.

Decision: [ADR 0022](adr/0022-explicit-temporal-meanings.md),
[issue #439](https://github.com/crpier/snekql/issues/439).
