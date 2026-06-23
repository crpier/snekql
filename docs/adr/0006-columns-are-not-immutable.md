# Columns are never immutable; the update builder guards only column ownership

Status: **Accepted**.

snekql does not model immutable columns. The update builder rejects an
assignment only when the column does not belong to the target model; generated
columns and primary-key columns are update-assignable like any other. This
extends [ADR 0005](0005-storage-primitive-constructors-with-derived-codecs.md)'s
stance — give users the freedom to shoot themselves in the foot, and let
violations surface at the database rather than be pre-empted by a library guard.

## Context

`GenCol` was introduced to model a *shape* difference for the type checker: a
column the database fills may be `Missing` on a Pending Model (`T | Missing`)
but is always present on a Fetched Model (`T`). That is its only purpose. The
runtime `is_generated` flag carries the shape semantics
(`Attr._coerce_missing_value`: `Missing` is allowed on Pending, an error on
Fetched) and gates `server_default=CurrentTimestamp` to a column whose shape can
actually be omitted at construction.

Separately, the update builder had grown a guard that rejected **both**
generated columns and primary-key columns from `UPDATE ... SET`
(`ensure_assignment_targets_model`). That guard conflated "the database fills the
default / the shape differs" with "the value is immutable after insert" — two
unrelated properties.

The conflation made the canonical "managed timestamp" unreachable. The two
`CurrentTimestamp` features lived on mutually exclusive column kinds:

- `server_default=CurrentTimestamp` (fill on insert from the DB clock) requires a
  generated column — it is only reachable on the omittable `T | Missing` shape;
- `.to(CurrentTimestamp)` (refresh on update from the DB clock) was *forbidden*
  on generated columns by the guard.

So an `updated_at` that both fills on insert and refreshes on update from the
database clock could not be declared on a single column.

## Decision

Remove the generated-and-primary-key clause from the update builder. After the
change:

- A generated column is update-assignable, both with a literal value and with
  `.to(CurrentTimestamp)`.
- A primary-key column is update-assignable. Updating a primary key is legal
  SQL; foreign-key breakage or constraint violations surface as database errors
  at execution, consistent with ADR 0005.
- `is_generated` retains exactly two jobs, neither of which is write-permission:
  the Pending/Fetched `Missing` coercion, and gating `server_default` to an
  omittable shape.

The canonical managed timestamp becomes a single column:

```python
updated_at: Memory.GenCol[datetime] = Text(
    server_default=CurrentTimestamp,
    default=MISSING,
)
```

omitted on insert (the database fills it), refreshed on update via
`Memory.updated_at.to(CurrentTimestamp)`, and overridable with an explicit value
in either place.

## Considered Options

- **Keep the block.** Rejected. It enforced an immutability that the database
  itself does not, and made the managed-timestamp use case unreachable.
- **Add a third column kind: server-default *and* writable.** Rejected. Once
  immutability is dropped, no new kind is needed — `GenCol` already carries the
  required shape. A new kind would enlarge the public column-alias surface for no
  benefit.
- **Drop the block; columns are never immutable.** Chosen.

## Consequences

- `created_at`-style generated columns and primary keys become overwritable.
  This is accepted: the library does not pretend to offer guarantees the database
  does not.
- `.to(CurrentTimestamp)` type-checks on any column regardless of its logical
  type (the overload accepts `type[CurrentTimestamp]` unconditionally). This
  pre-existing footgun is unchanged and left to runtime, per ADR 0005.
- The test pinning the old behavior (`update_rejects_generated_and_primary_key_assignments`)
  is inverted to assert the assignments now succeed.
