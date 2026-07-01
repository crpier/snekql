# Datetime-over-text is canonicalized to a UTC millisecond instant

Status: **Accepted**. Amends [ADR 0005](0005-storage-primitive-constructors-with-derived-codecs.md)
for the `datetime`-stored-as-`TEXT` case; the rest of ADR 0005 stands.

## Context

ADR 0005 delegated SQLite value semantics to Pydantic wholesale: a
`Col[datetime] = Text()` encoded with `adapter.dump_python(mode="json")`,
preserving the value's original offset and microsecond precision, and round-trip
of a naive datetime stayed naive ("timezone/precision is the logical type's
job"). That is defensible for *storage round-trip* but silently breaks
*querying* (#212).

SQLite stores datetimes as ISO **text** and compares text **lexically**, not by
instant. Pydantic's json form is not canonical, so the same instant serializes
to different strings depending on who wrote the row and how:

| source | stored text for `2026-07-01 12:00:00 UTC` |
|---|---|
| `CurrentTimestamp` server default (`strftime('%Y-%m-%dT%H:%M:%fZ','now')`) | `2026-07-01T12:00:00.000Z` |
| client, whole second | `2026-07-01T12:00:00Z` |
| client, microseconds | `2026-07-01T12:00:00.678999Z` |
| client, `+05:30` offset (same instant) | `2026-07-01T17:30:00+05:30` |
| client, naive | `2026-07-01T12:00:00` |

Consequences of lexical comparison over that heterogeneity:

- **Equality misses.** `12:00:00Z` ≠ `12:00:00.000Z` (client whole-second vs the
  server default) even though both are the same instant, so a row inserted by
  one path is not found by an equality predicate built from the other.
- **`ORDER BY` and range predicates are wrong.** A `+05:30` row's text starts
  `...T17:30`, so it sorts after a *later* `13:00Z` instant and is wrongly
  included by a `>= 13:00Z` range even though it is 12:00 UTC.

## Decision

**A `datetime` stored over primitive `TEXT` is normalized on encode to a UTC
instant at fixed millisecond precision**, sharing the exact contract the MariaDB
native `DateTime` type already had (see #211):

- convert to UTC (`astimezone(UTC)`); the stored text is a bare instant with no
  offset variation;
- floor microseconds to milliseconds (`microsecond // 1000`), matching the
  `strftime('%f')` server default's 3-digit resolution and MariaDB `DATETIME(3)`;
- reject a **naive** input with `ModelValidationError` — it has no offset to
  reduce to an instant, so `astimezone` would silently assume the write
  machine's local zone (the asymmetric, machine-dependent round-trip #211
  removed for MariaDB). Awareness is opt-in via `Col[AwareDatetime]` or a
  tz-attached value.

On SQLite this yields `2026-07-01T12:00:00.000Z`, byte-identical to the
`CurrentTimestamp` server default, so client-written and server-written rows
finally coincide and lexical TEXT comparison equals instant comparison. The dead
`_decode_sqlite_datetime` codec (dispatched only for a `DateTime` storage type
SQLite no longer has, per ADR 0005) is **wired up** as the decode side of this
form: it enforces the `...Z` shape and parses it back to an aware UTC datetime.

The change keys on `(logical type is datetime, storage is TEXT)`, so it also
covers a MariaDB `Col[datetime] = Text()` opt-in (canonicalized with that
backend's space-separated codec) — the two backends' datetime-over-text columns
become symmetric. It does **not** touch a custom epoch type over `Integer()`
(logical type is the user's type, not `datetime`), which keeps its Pydantic
round-trip.

## Considered options

- **Canonical UTC millisecond form (chosen).** Lexical comparison becomes
  instant comparison; precision and the server-default/client mismatch collapse;
  the dead codec resolves. Cost: reverses ADR 0005's "naive round-trips naive"
  and "SQLite preserves offset/microseconds" for this one case, and adds a naive
  rejection.
- **Document the lexical semantics; steer users to `Col[AwareDatetime]` + UTC
  discipline.** Rejected: insufficient. Even all-UTC data breaks, because
  Pydantic's variable precision (`12:00:00Z` vs the server default
  `12:00:00.000Z`) mis-orders same-second values. Fixing that requires pinning
  precision — i.e. most of the canonicalization anyway.
- **Normalize in the query (wrap columns in SQLite `datetime()`).** Rejected: it
  defeats indexes and SQLite's date functions do not reliably parse `+05:30`
  offsets. Storage-side canonicalization is the correct layer.

## Consequences

- **Breaking.** A naive `datetime` on a datetime-over-text column now raises;
  stored text is UTC with no offset; sub-millisecond precision is lost by design
  (floors to ms, matching MariaDB and the server default). Values read back are
  aware UTC.
- **Sub-minute offsets are now accepted**, superseding ADR 0005's rejection: the
  offset is folded into the UTC instant on conversion, so the stored `...Z` text
  carries nothing left to truncate.
- **ADR 0005's "intentional precision and representation loss" note now also
  applies to SQLite `Col[datetime] = Text()`**, not only MariaDB `DateTime`.
- **The `pydantic.Json[datetime]` path is unchanged** — a JSON payload is not a
  comparison-sortable storage column, so it keeps Pydantic's serialization.
