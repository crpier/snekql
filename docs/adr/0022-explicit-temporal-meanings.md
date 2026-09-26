# Explicit temporal meanings and exact storage precision

Status: accepted. Supersedes [ADR 0009](0009-utcdatetime-curated-logical-type.md)'s
annotated UTC alias, millisecond normalization, and bare-datetime escape hatch.
Preserves [ADR 0012](0012-zoned-datetime-identity.md)'s resolved zoned identity.

Use immutable `UtcDatetime`, `LocalDatetime`, and `ZonedDatetime` values with uniform
construction and `.datetime` access. Keep calendar dates as Python `date`. Immediate
invariants and nominal UTC/local distinctions justify explicit wrapper calls; aliases
would retain inconsistent construction and erase the distinction for the checker.

Annotations own temporal meaning. MariaDB gains native `Date()` and
`DateTime(precision=6)`; SQLite keeps physical `Text()` storage. Preserve application
microseconds, reject lossy lower-precision writes, and retain full-precision predicate
bounds. Database clock resolution does not determine storage precision.
`CurrentTimestamp` supplies only UTC instants through column-aware SQL.

Canonical UTC/civil text uses six fractional digits. Applications must migrate rows,
defaults, and external writers deliberately: tolerant decoding cannot fix SQL
comparisons over mixed-width text. No implicit timezone inference, automatic data
migration, or scheduling policy is provided. See the
[contract and upgrade guide](../temporal-contracts.md) and
[issue #439](https://github.com/crpier/snekql/issues/439).
