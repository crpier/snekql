# Instant: a curated logical type with an order-preserving wire form

Status: **Accepted**. Extends
[ADR 0005](0005-storage-primitive-constructors-with-derived-codecs.md).
Origin: issue #212.

Over SQLite `Text()` storage, SQL compares datetime columns as text. Pydantic's
default datetime wire form preserves the input's offset and precision, so two
encodings of the *same instant* (`...+05:30` vs `...Z`, `.1` vs `.100000`)
disagree under `=`, `ORDER BY`, and range predicates. ADR 0005 deliberately moved
logical semantics out of the codec and into pydantic types; the fix therefore
ships as a **snekql-exported curated pydantic type**, not as codec behavior. This
is additive to 0005, not a reversal: the codec stays a thin wire-shaper; snekql
simply starts curating a logical type where the default wire form breaks storage
semantics.

## Decision

snekql exports **`Instant`**, a curated Logical Type for an absolute point in
time:

- **Aware-only.** Naive datetimes are rejected at validation. Bare
  `Col[datetime]` remains the sanctioned naive wall-clock escape hatch.
- **Lax in, canonical out.** Any aware offset is accepted (`+05:30` is fine) and
  the in-memory value may keep it; *serialization* normalizes to UTC. Anything
  that has been through the database comes back `+00:00`.
- **Millisecond precision**, wire form `YYYY-MM-DDTHH:MM:SS.sssZ` — an
  **order-preserving wire form**: lexical text order equals instant order, which
  is what makes SQLite `Text()` equality, ordering, and range queries correct.
- **No new server default.** The existing `CurrentTimestamp` marker already
  emits `strftime('%Y-%m-%dT%H:%M:%fZ','now')` (ms + `Z`) on SQLite and
  `CURRENT_TIMESTAMP(3)` into `DATETIME(3)` on MariaDB, so it matches `Instant`
  byte-for-byte (SQLite) / by-instant (MariaDB). Millisecond precision was
  chosen *because* it makes the existing default line up.
- A **suppressible warning** fires when a SQLite `Text()` column carries a
  datetime logical type without an order-preserving wire form — bare `datetime`
  and pydantic `AwareDatetime` both qualify (both are lexically unsafe). No
  warning for `Instant`, and none on MariaDB native `DateTime`, which the engine
  already compares by instant.

## Corrected empirical claims (supersede the text of #212)

Verified this design round against MariaDB 12.2 (`temporary_mariadb_server()`)
and local SQLite:

1. **MariaDB truncates fractional seconds by default** (`.9995 → .999`);
   rounding requires opting into `TIME_ROUND_FRACTIONAL` in `sql_mode`. The
   issue's claim that "MariaDB rounds half-up" is **MySQL** behavior, wrongly
   attributed. snekql's `microsecond // 1000` floor already matches MariaDB.
2. **MariaDB native `DATETIME` compares by instant, not lexically.** The
   lexical-comparison hazard is SQLite-`Text()`-specific.
3. **SQLite `strftime` caps fractional output at milliseconds** (even the
   3.42+ `subsec` modifier yields 3 digits), so a microsecond server default is
   impossible on SQLite. This is what rules out microsecond precision.

## Considered options

- **Microsecond precision.** Rejected: SQLite cannot server-default beyond ms
  (finding 3), and MariaDB would need `DATETIME(6)` plumbing plus a new default.
  Revisit only for a MariaDB-native `DATETIME(6)` use case.
- **Offset-preserving order-safe wire form** (composite `...Z|+05:30`).
  Rejected: SQL `=` would then disagree with Python's instant-based `==` for
  equal instants written from different offsets — a real footgun. Users who need
  the writer's offset back store it explicitly (second column, or a future
  opt-in composite type that documents the `=` caveat).
- **Retiring `AwareDatetime`.** Not ours to retire — it is pydantic's, and
  ADR 0005 lets users annotate any type. `Instant` supersedes it *as the
  recommendation*, not as a type: `AwareDatetime` does not fix the comparison
  hazard it is currently suggested for. Its remaining honest niche vs `Instant`
  is an audit/display column that preserves the writer's offset and is never
  ordered or range-queried.
- **A curated bool.** Rejected: `Col[bool] = Integer()` (0/1) already orders and
  round-trips correctly — no hazard, so no curated type. `Decimal` over `Text()`
  has the same lexical hazard as datetime and is the real next analog; noted,
  out of scope here.

## Consequences

- Code and docs that currently point users at `AwareDatetime` as the fix (e.g.
  the MariaDB naive-rejection error message in `storage.py`) redirect to
  `Instant`.
- The dead `_decode_sqlite_datetime` path (never dispatched since SQLite lost
  its `DateTime` storage type in ADR 0005) is wired up or deleted as part of
  this work.
- Precedent: snekql ships a curated logical type only where a storage primitive
  has a genuine comparison or precision hazard — not for interface uniformity.
  Generalizing this into a library-wide principle is deliberately left to a
  follow-up decision.
