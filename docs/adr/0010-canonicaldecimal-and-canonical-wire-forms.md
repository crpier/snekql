# CanonicalDecimal and the canonical/order-preserving wire-form taxonomy

Status: **Accepted**. Generalizes
[ADR 0009](0009-utcdatetime-curated-logical-type.md) into a library-wide
principle. Origin: issue #215.

`Decimal` over `Text()` is the second logical type with a genuine storage
hazard. Pydantic's default wire form preserves the input's representation, not
its value: `Decimal("1.50")` → `'1.50'` but `Decimal("1.5")` → `'1.5'`,
`Decimal("1E+2")` → `'1E+2'` (not `'100'`), and `Decimal("-0")` → `'-0'` (all
verified against pydantic 2.13). Same number, different text: db-side `=`,
`IN`, and unique indexes miss — the exponent form is not even lexically
comparable with plain digits. Lexical ordering is additionally wrong for *any*
plain decimal text (`'10' < '9'`, negatives sort backwards). Both backends are
affected: a `Text()` decimal is VARCHAR on MariaDB and compares by collation,
so unlike the datetime hazard this one is not SQLite-specific.

Unlike `UtcDatetime`, there is no free order-preserving encoding: lexical
order-safety for decimals requires fixed precision/scale (zero-padded integer
part) and complement-encoding of negatives — declared parameters and an
unreadable stored form. There *is* a free **canonical** encoding, which fixes
equality but not ordering. That asymmetry drives the whole design: the two
safety levels are named, marked, and warned about separately.

## Decision

### The taxonomy (the ADR 0009 precedent, generalized)

- A **Canonical Wire Form** encodes each logical value as exactly one text, so
  db-side `=`, `IN`, and unique indexes agree with the Logical Type's equality.
- An **Order-Preserving Wire Form** is additionally lexically ordered like the
  logical values. Order-preservation implies canonicality (two distinct texts
  for one value cannot both order correctly against everything else), so the
  levels nest.
- The markers mirror the nesting: a new public **`Canonical`** annotation
  marker, with the existing `OrderPreserving` redeclared as its subclass. Like
  `OrderPreserving`, `Canonical` is a self-certified claim snekql does not
  verify. Both export from each Backend Namespace.
- The library-wide principle, stated once: **snekql ships a curated logical
  type only where a storage primitive has a genuine comparison or precision
  hazard, normalizing at validation per ADR 0009's rule; declaration-time
  advisory warnings key on the marker taxonomy; and where an engine can
  enforce the semantics natively, the Backend Namespace grows a native Column
  Type instead of a cleverer text encoding.**

### CanonicalDecimal

snekql exports **`CanonicalDecimal`**, a curated Logical Type for exact decimal
values, backend-blind and re-exported by both Backend Namespaces as the same
alias (the ADR 0009 export pattern):

- **Normalize at validation** to the canonical minimal plain form: no exponent,
  no trailing fractional zeros, no negative zero (`1.50` → `1.5`, `1E+2` →
  `100`, `-0` → `0`). This is numerically lossless — `Decimal.__eq__` ignores
  scale — so it is strictly *less* lossy than `UtcDatetime`'s millisecond
  truncation. The value a model holds, the value stored, and the value fetched
  back are identical. Non-finite values (`NaN`, `Infinity`) are already
  rejected by pydantic's `Decimal` validation.
- **Carries `Canonical`, not `OrderPreserving`.** Equality, `IN`, and unique
  indexes over `Text()` become correct; `ORDER BY` and range predicates remain
  documented-unsafe. A curated type must not claim safety it does not have.
- **Deliberately drops the input's scale.** A `Decimal`'s scale is presentation
  metadata; `CanonicalDecimal` is a database-interaction type, not a display
  type (ADR 0009's framing). Callers who need a fixed displayed scale quantize
  at the presentation boundary, or use the MariaDB native `Decimal` column.

### The warning

- A suppressible **`LexicalDecimalWarning`** (sibling of
  `LexicalDatetimeWarning`) fires at model declaration time when a `Text()`
  column carries a `Decimal` logical type whose metadata lacks at least the
  `Canonical` marker.
- It fires on **both backends**, diverging from the datetime warning's
  SQLite-only scope. The datetime warning exempts MariaDB because native
  `DateTime` compares by instant; a `Text()` decimal has no such native escape
  on either backend — the hazard follows the storage, not the engine.
- The message points at `CanonicalDecimal` for equality and at integer minor
  units / MariaDB native `Decimal` for ordering.

### MariaDB native `Decimal(precision, scale)` Column Type

The MariaDB Backend Namespace grows a native `Decimal(precision, scale)`
constructor emitting `DECIMAL(p,s)` — the engine compares numerically, fixing
equality *and* ordering *and* SQL aggregation (`_normalize_sum` already
anticipates MariaDB `DECIMAL` sums):

- This is snekql's **first parameterized Column Type** (`Text()` is a fixed
  `VARCHAR(255)`). The cost lands in schema verification — the column shape
  must carry `NUMERIC_PRECISION`/`NUMERIC_SCALE` from `information_schema` —
  and scaffold DDL, not in the codec.
- **Encode rejects values that do not fit `(p, s)`** with a domain error,
  mirroring the existing `max_text_chars` reject-don't-truncate rule, rather
  than letting MariaDB round. Rounding at encode would silently break
  held == stored == fetched, and silent money rounding is the worst available
  failure mode.
- Ships as a separate implementation unit; this ADR fixes the design so the
  curated type and warning are not blocked on it.

### Integer minor units: docs guidance, not a type

The documented recommendation for SQLite columns that need ordering, range
predicates, or SQL aggregation is integer minor units (`Col[int] = Integer()`,
e.g. cents) with conversion at the application boundary.

## Considered options

- **A curated scaled-integer logical type** (a `Decimal` validating/serializing
  as minor-unit `int` over `Integer()`). Rejected: inside a pydantic validator,
  a fetched database `150` (meaning `1.50`) and a user-constructed `150`
  (meaning `150`) are indistinguishable, and ADR 0005 forbids pushing that
  read/write asymmetry into the codec. The conversion stays at the application
  boundary.
- **A fully order-preserving decimal text encoding** (fixed-width, zero-padded,
  sign-complemented negatives). Rejected: requires declared parameters, stores
  an unreadable form, and still cannot `SUM`. Anyone needing ordering is better
  served by minor units (SQLite) or native `DECIMAL` (MariaDB). A user who
  builds one anyway can self-certify it with `OrderPreserving`.
- **Preserving the input's scale by padding to a declared scale.** Rejected:
  needs parameters on a Logical Type, duplicating what the MariaDB native
  column declares as storage metadata, for a presentation concern the type
  explicitly does not own.
- **Warning at query-compile time** (only when an `ORDER BY`/range predicate
  actually touches an unsafe column). Rejected for now: ADR 0009 chose loud,
  early, once-per-class declaration-time warnings because the curated type is
  the recommended practice even before anything orders the column; a
  compile-time channel would be new machinery for a weaker nudge.
- **Naming the curated type `Decimal`.** Rejected: it would collide with
  `decimal.Decimal` at every model declaration site. The MariaDB *constructor*
  keeps the engine's name (`Decimal(p,s)`, like `DateTime`, `Uuid`) because
  constructors are used namespace-qualified.

## Consequences

- `OrderPreserving` becomes a subclass of `Canonical`; existing marker
  detection must accept the subclass relationship. No public behavior changes
  for `UtcDatetime`.
- Docs gain a decimal-storage section covering the three-way choice:
  `CanonicalDecimal` for identity/equality columns, minor units for SQLite
  ordering/aggregation, native `DECIMAL(p,s)` on MariaDB.
- Precedent confirmed and bounded: curated types exist to defuse storage
  hazards, not for interface uniformity; the next candidate must name its
  hazard first.
