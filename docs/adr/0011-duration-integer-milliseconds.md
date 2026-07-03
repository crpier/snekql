# Duration: a curated logical type stored as integer milliseconds

Status: **Accepted**. Applies the [ADR 0010](0010-canonicaldecimal-and-canonical-wire-forms.md)
curated-type principle. Origin: issue #216; the design shipped in PR #220
without an ADR as a deliberate scoping decision, and this records it
retroactively as shipped at the head of that PR (including review-fix
`3ce51c5`).

`timedelta` is the third logical type to name a genuine storage hazard, as ADR
0010 requires of any new curated-type candidate. Pydantic's json-mode wire form
for a bare `timedelta` is ISO-8601 duration text (`timedelta(seconds=9)` →
`'PT9S'`). Over `Text()` that round-trips, but database-side ordering is lexical:
`'PT10S' < 'PT1H' < 'PT9M' < 'PT9S'`, so ascending SQL order disagrees with
elapsed-time magnitude on both backends. That is the ADR 0010 gate's "genuine
comparison hazard".

The repro for #216 narrows the hazard to that one path. The suspected
`Integer()`-path hazard — silent storage or coercion of the duration text into a
numeric column — did **not** reproduce: snekql-created schemas are strict on both
backends (SQLite `STRICT` tables, MariaDB `STRICT_ALL_TABLES`) and reject the
text at insert (`IntegrityError: cannot store TEXT value in INTEGER column`;
`DataError 1366`). That path fails safe rather than storing lies, so only the
`Text()` lexical-order hazard is real.

Unlike `UtcDatetime` and `CanonicalDecimal`, a `timedelta` is a pure magnitude,
so its free equality- *and* order-safe encoding is not a cleverer text form at
all — it is a signed integer of total milliseconds over an integer storage
class, where the engine already compares numerically. `Duration` is therefore
the first curated type that defuses its hazard by choosing a non-text storage
class rather than by shaping text, the ADR 0010 principle that where an engine
enforces the semantics natively snekql reaches for storage, not a text encoding.

## Decision

snekql exports **`Duration`**, a curated Logical Type for an elapsed span of
time, backend-blind and re-exported by both Backend Namespaces as the same alias
(the ADR 0009 export pattern):

- **Millisecond canon.** Normalize at validation to a whole-millisecond
  `timedelta`, matching `UtcDatetime`'s millisecond precision ([ADR
  0009](0009-utcdatetime-curated-logical-type.md)). Sub-millisecond precision is
  truncated toward negative infinity (floor), so `-0.5 ms` canonicalizes to
  `-1 ms`, not `0` — consistent across the sign. The value a model holds, the
  value stored, and the value fetched back are identical.
- **Integer wire form.** Serialized as a signed integer of total milliseconds,
  intended for `Integer()` storage. Over an integer column the engine compares
  numerically, so `=`, `ORDER BY`, and range predicates all agree with
  elapsed-time order — equality and ordering defused together, the split that
  forced `CanonicalDecimal` to ship only equality does not arise here.
- **Decode rule, and its construction asymmetry.** An integer database value is
  interpreted as milliseconds by a `BeforeValidator`. This is necessary: pydantic's
  lax bare-`timedelta` validation reads a plain `int` as *seconds*, so without the
  before-validator a fetched `9000` would decode as 9000 seconds, not 9 s. The
  same validator runs at model construction, so `Duration(...=9000)` also means
  9000 milliseconds — a deliberate, documented asymmetry: a raw `int` handed to a
  `Duration` field is the wire unit (milliseconds), unlike a bare `timedelta`
  field. Callers pass a `timedelta` to avoid the question.
- **The signed-64-bit range guard for free.** Because the wire form is an `int`,
  the existing integer range guard applies unchanged; a duration whose
  millisecond count overflows signed 64 bits is rejected at encode rather than
  silently wrapping.

### Marker: `Duration` carries no marker

- **Order-preserving over `Integer()`, but not text-order-safe.** Integer wire
  order equals duration order when the column is `Integer()`. But the bare
  integer serialized *as text* sorts lexically (`"10000"` before `"9000"`,
  negatives inverted). The `OrderPreserving` marker's contract is text-column
  comparison-order safety, which the wire form does not have over `Text()`, so
  `Duration` deliberately does **not** carry it — mirroring `CanonicalDecimal`
  carrying only `Canonical`, per ADR 0010's rule that a curated type must not
  claim safety it does not have.
- It carries no `Canonical` either: that marker certifies `Text()`-storage
  equality, and the integer wire form is not meant for `Text()` at all.
- **Consequence:** `Col[Duration] = Text()` emits `LexicalDurationWarning`,
  exactly as a bare `timedelta` over `Text()` does; `Col[Duration] = Integer()`
  never warns. Reaching for `Duration` does not buy out of the warning if the
  value is still stored as text — the warning keys on the wire form's real
  safety over the storage class, not on the type's name.

### The warning

- A suppressible **`LexicalDurationWarning`** (sibling of
  `LexicalDatetimeWarning` and `LexicalDecimalWarning`) fires at model
  declaration time when a `Text()` column carries a `timedelta` logical type
  whose metadata lacks a text-order-preserving wire form.
- It fires on **both backends**, like the decimal warning and unlike the
  SQLite-only datetime warning: a `Text()` duration is `VARCHAR` on MariaDB and
  `TEXT` on SQLite, and neither engine has a native escape for the integer wire
  form stored as text — the hazard follows the storage, not the engine.
- The message points at `Integer()` storage, where integer order equals duration
  order.

## Considered options

- **Carrying `OrderPreserving` on `Duration`.** This is what the type shipped
  with initially and what review-fix `3ce51c5` removed. The marker claimed
  text-column order safety the integer wire form does not have, and — worse —
  carrying it silenced the lexical-storage detector for a genuinely order-unsafe
  `Duration`-over-`Text()` declaration. Removing it is what makes the warning
  fire correctly on the misuse path while `Duration` over `Integer()` stays
  silent (the detector early-returns on non-`TEXT` storage).
- **An order-preserving decimal-style text encoding** (fixed-width, zero-padded,
  sign-complemented milliseconds). Rejected for the same reason as the decimal
  case: it stores an unreadable form and needs declared width, when the
  `Integer()` storage class already yields numeric ordering for free.
- **A whole-second canon / integer-seconds wire form.** Rejected: it diverges
  from `UtcDatetime`'s millisecond canon and silently drops sub-second precision,
  which is common for elapsed-time measurements.
- **Decoding an integer database value as seconds** (matching pydantic's lax
  default rather than adding the `BeforeValidator`). Rejected: it would make the
  wire unit disagree with itself — encode writes milliseconds, decode would read
  seconds — breaking held == stored == fetched by a factor of 1000.

## Consequences

- `Duration` is the recommended `timedelta` type for database columns; bare
  `Col[timedelta]` remains available as the ISO-text escape hatch, now flagged
  by `LexicalDurationWarning` when stored over `Text()`. The error-handling guide
  documents the warning alongside its datetime and decimal siblings, and
  `CONTEXT.md` gains the `Duration` glossary entry (both in PR #220).
- The construction-time int-as-milliseconds rule is a documented sharp edge: a
  raw `int` passed to a `Duration` field is milliseconds, and callers who want to
  be unambiguous pass a `timedelta`.
- Precedent held and extended: this is the third curated type and the first to
  defuse its hazard by choosing a non-text storage class (`Integer()`) rather
  than shaping text. ADR 0010's principle that a curated type must not claim
  safety it does not have is enforced directly by `Duration` carrying no marker.
