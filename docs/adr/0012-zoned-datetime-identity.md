# ZonedDatetime preserves instant and timezone identity

Status: **Accepted**. Extends [ADR 0009](0009-utcdatetime-curated-logical-type.md).
Origin: issue #237.

`UtcDatetime` models an absolute instant and deliberately erases the input timezone. That is wrong for civil schedules, audit context, and display values where `America/New_York` carries domain meaning beyond its current UTC offset. Pydantic `AwareDatetime` does not solve this because ISO datetime text records only an offset and cannot reconstruct an IANA zone after fetching.

`ZonedDatetime` is a value object containing an aware `datetime`. It accepts `zoneinfo.ZoneInfo` and fixed-offset `datetime.timezone` values, and rejects timezone implementations without a stable persistence identity. Its identity and equality are the pair of the UTC instant and exact timezone descriptor. IANA aliases remain distinct, and an IANA zone remains distinct from a fixed offset even when their current offsets match. This deliberately differs from Python `datetime` equality, which compares aware values by instant.

The Canonical Wire Form is versioned text containing a microsecond UTC instant, timezone kind, and timezone value. IANA values store the exact `ZoneInfo.key`; fixed zones store their offset in integer microseconds. Reconstructing an IANA value from the instant and key restores the correct local time and ambiguous-time `fold`. Both backends store this form with `Text()`. MariaDB `DateTime()` cannot preserve timezone identity.

SQL equality, inequality, membership, and unique indexes follow `ZonedDatetime` equality because equal values have identical text. Ordering, ranges, `MIN`, and `MAX` are rejected because the complete Canonical Wire Form has no lexical order matching instant order. `UtcDatetime` remains the type for chronologically ordered timestamp columns.
