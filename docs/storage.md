# Choose how values are stored

A column declaration answers two different questions:

```python
# Inside a SQLite model:
created_at: sqlite.Col[sqlite.UtcDatetime] = sqlite.Text()
```

`UtcDatetime` describes the Python value and how it is validated. `Text()` says
where SQLite stores it. snekql chooses the conversion between them; you do not
write a separate encoder for every column.

Start with [models](models.md) if you have not declared a table yet.

## Common choices

| Value you need | SQLite | MariaDB |
| --- | --- | --- |
| Integer | `Col[int] = Integer()` | `Col[int] = Integer()` |
| Floating-point number | `Col[float] = Real()` | `Col[float] = Real()` |
| Text | `Col[str] = Text()` | `Col[str] = Text(length=...)` |
| Bytes | `Col[bytes] = Blob()` | `Col[bytes] = Blob()` |
| Boolean | `Col[bool] = Integer()` | `Col[bool] = Boolean()` |
| Calendar date | `Col[date] = Text()` | `Col[date] = Date()` |
| Local civil datetime | `Col[LocalDatetime] = Text()` | `Col[LocalDatetime] = DateTime()` |
| Timestamp ordered by instant | `Col[UtcDatetime] = Text()` | `Col[UtcDatetime] = DateTime()` |
| UUID | `Col[UUID] = Text()` or `Blob()` | `Col[UUID] = Uuid()` or `Blob()` |
| JSON | `Col[Json[Payload]] = Text()` | `JsonCol[Payload] = Json()` |
| Exact numeric decimal calculations | Integer minor units, such as cents | `Col[Decimal] = Decimal(precision, scale)` |

Import constructors and annotations from the matching backend. In the decimal
row, the annotation is Python's `decimal.Decimal`; the constructor is
`mariadb.Decimal(...)`. In the JSON row, `Json[Payload]` is Pydantic's marker.

SQLite has only `Integer`, `Real`, `Text`, and `Blob` storage constructors.
MariaDB also offers native `Boolean`, `Date`, `DateTime`, `Decimal`, `Json`, `Uuid`, and
`LongText`. Picking a Python type does not give SQLite a missing native type.

Validation cannot make every pairing useful. Some mismatches fail only when
encoding a write or decoding a read. Pick a representation whose database
comparison rules match the queries you need.

## Dates and datetimes

Use Python `date` for a calendar date. For datetime values, choose the meaning
explicitly:

```python
from datetime import UTC, datetime
from snekql.sqlite import LocalDatetime, UtcDatetime

occurred_at = UtcDatetime(datetime.now(UTC))
opens_at = LocalDatetime(datetime(2026, 10, 1, 9, 0))
```

`UtcDatetime` normalizes an aware input immediately and retains microseconds.
`LocalDatetime` keeps timezone-free civil fields without inventing an instant.
Both are immutable values exposing the standard datetime through `.datetime`.
Bare datetime temporal declarations are rejected rather than warned about.

MariaDB `DateTime(precision=6)` supports both meanings. Lower precision rejects
lossy writes but does not truncate query bounds. UTC and local values cannot be
compared to one another implicitly.

Use `ZonedDatetime` for a resolved instant whose exact IANA zone key or fixed
offset matters. Store it in `Text()` on either backend. Equality, membership, and
unique indexes work; chronological ordering, ranges, MIN, and MAX are rejected.
Anonymous `ZoneInfo` objects without a persistent key are rejected. The instant
must fit Python's UTC datetime range, even when the local datetime is valid.
A resolved zoned value is not a recurring schedule.

Read [dates and datetimes](temporal-contracts.md) for construction rules, canonical
formats, clocks, native ranges, and the required migration from millisecond text.

For elapsed time, `Col[Duration] = Integer()` stores signed whole milliseconds
and normalizes Python timedeltas to that precision. It is a duration, not a
wall-clock timestamp.

## Decimals: choose equality or numeric calculations

For money in SQLite, integer minor units are often the simplest choice when you
need sorting, sums, or range filters. Decide the unit in your application and
keep it consistent.

On MariaDB, `mariadb.Decimal(precision, scale)` gives numeric database behavior.
Writes that would overflow or require rounding are rejected before driver I/O.
SUM comparison bounds may be wider than an individual input column, while writes
still obey that column's precision and scale.

For portable exact equality, use `Col[CanonicalDecimal] = Text()`. It stores a
single text representation for each value: `1.50` becomes `1.5`, `1E+2` becomes
`100`, and negative zero becomes zero. Equality, IN, and unique indexes are safe.
Text ordering is still not numeric ordering.

Plain `Col[decimal.Decimal] = Text()` emits `LexicalDecimalWarning`. Ordinary
Pydantic decimal text can represent equal numbers differently. A custom logical
type marked `Canonical` or `OrderPreserving` must actually uphold that promise;
the marker does not change the representation for you.

## JSON values

Pass decoded Python values, not JSON strings. A payload can contain types that
Pydantic knows how to validate and serialize, including dates and Pydantic models.
It is not limited to untyped dictionaries.

SQLite uses Pydantic's `Json[Payload]` annotation over `Text()`. MariaDB can use
`JsonCol[Payload]` with native `Json()`, or the text representation.

For optional fields, see [SQL NULL versus JSON null](optional-json.md). They are
not the same stored value, even when both read back as Python `None`.

## UUIDs

`Text()` stores UUID strings; `Blob()` stores the UUID's 16 bytes in UUID byte
order. MariaDB also has native `Uuid()` storage. Pydantic's UUID-version types,
such as `UUID4` or `UUID7`, add version validation without changing that storage.

Match default factories to the version you require. A `uuid4` factory on a UUID7
field fails validation; the annotation does not rewrite the factory's output.

Older MariaDB UUID Blob data may contain ASCII UUID text. Reads can accept it,
but binary equality predicates will not match it. Follow the
[binary UUID migration guide](binary-uuid-migration.md) before upgrading those rows.

## Database defaults

Use a `GenCol` when the database may supply a value. `CurrentTimestamp` asks it
for the current UTC instant on a `UtcDatetime` column; `LiteralDefault(value)` declares a supported SQL
literal default. Both are different from Python's `default=value`.

Omitted generated values stay `PENDING_GENERATION` in the Pending object. Use
SELECT or RETURNING to read what the database supplied. You can also pass an
explicit value; a default is not a write-protection rule.

To refresh a timestamp during UPDATE, assign the marker explicitly:

```python
# Suppose Document.edited_at is a timestamp column.
query = (
    sqlite.update(Document)
    .set(
        Document.edited_at.to(sqlite.CurrentTimestamp),
    )
    .where(Document.id.eq(document_id))
)
```

This uses the database clock. SQLite has no automatic ON UPDATE equivalent here;
include the assignment in every update that should refresh the timestamp.

## Indexes and foreign keys

Use `unique=True` for a column-level unique index, or `index=True` for an ordinary
single-column index. Primary keys are already indexed. `index=True` cannot be
combined with `unique=True`, and primary-key columns reject those redundant flags.

Use `__indexes__` for multiple columns or an explicit name:

```python
from typing import ClassVar

from snekql import sqlite


class Contact[State = sqlite.Pending](sqlite.Model[State]):
    __row_type__: ClassVar[sqlite.ReadType[Contact[sqlite.Row]]]
    tenant_id: sqlite.Col[int] = sqlite.Integer()
    email: sqlite.Col[str] = sqlite.Text()

    __indexes__ = [
        sqlite.Index(tenant_id, email, unique=True),
    ]
```

An index does not change the live table by itself. Commit the corresponding SQL
in a [migration](migrations.md). Do not declare the same index twice through both
a column flag and `__indexes__`.

A scalar foreign key needs a target that is unique **on its own**. Being one part
of a composite primary key or multi-column unique index is not enough. Use a
[table-level foreign key](typing.md#table-level-foreign-key-constraints) when the
relationship depends on several columns. Do not make a field unique merely to
satisfy the checker if repeated values are legitimate.

The [declaration reference](typing.md) covers CHECK constraints, composite keys,
collations, partial indexes, and MariaDB prefix indexes. [Schema verification](schema-drift.md)
explains which of those facts snekql can check and which remain unchecked.

[All guides](README.md)
