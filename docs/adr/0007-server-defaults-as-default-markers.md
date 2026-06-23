# Server defaults are declared as `default` markers, not a `server_default` parameter

Status: **Accepted**. Supersedes the `server_default` open question in
[ADR 0005](0005-storage-primitive-constructors-with-derived-codecs.md).

A server default is declared by passing a distinguished marker as a column's
`default` -- `Text(default=CurrentTimestamp)` -- not through a separate
`server_default=` constructor parameter. The metaclass detects the marker, routes
it to the internal server default, and leaves the column omittable at
construction. The public `server_default=` parameter is removed from every column
constructor on both backends.

## Context

Constructors exposed a `server_default` parameter whose only legal value was
`CurrentTimestamp`, and every such column also had to be written with
`default=MISSING`:

```python
created_at: GenCol[datetime] = Text(server_default=CurrentTimestamp, default=MISSING)
```

The `default=MISSING` looked like redundant boilerplate, but it is **load-bearing
for the type checker**. Under PEP 681, pyright treats a dataclass-transform field
as optional in `__init__` *only* when the field-specifier call passes one of
`default` / `default_factory` / `factory`. We verified empirically that nothing
else works: a field-specifier whose `default` parameter merely *defaults* to a
non-`...` value still produces a required field, and overloads selected by
`server_default=` do not change it. So `server_default=` alone can never make a
field optional -- the `default=MISSING` was the actual optionality signal, and
omitting it left the field required (a `Memory(...)` call error) even though the
database supplies the value.

That made the two `CurrentTimestamp` features awkward to reconcile and forced the
redundant pairing on every server-filled column.

## Decision

Remove the public `server_default` parameter. Declare a server default by passing
a marker through `default`, which pyright already recognizes:

```python
created_at: GenCol[datetime] = Text(default=CurrentTimestamp)
```

The metaclass detects `default is CurrentTimestamp`, sets the internal
`Attr.server_default`, and resets the construction default to `MISSING` -- so the
field is optional for the type checker, omittable at runtime (the database fills
it), and still accepts an explicit value. The internal `server_default` attribute
that schema DDL and compilation read is unchanged.

This unifies the default surface: **every default flows through `default=` /
`default_factory=`.** A plain value is a Python default, a factory is a Python
factory, and a distinguished marker is a server default. It reverses the prior
guard that forbade `default=CurrentTimestamp`.

Rules retained: a server-default column must be a Generated Column (`GenCol`) --
its Pending value may be `Missing` -- and cannot also carry a `default_factory`.
`auto_increment` is unchanged and still pairs with `default=MISSING` (it has no
value-marker).

## Considered Options

- **Make `server_default=` imply an optional field.** Rejected: type-checker
  infeasible. PEP 681 keys field optionality off the `default`/`default_factory`/
  `factory` arguments in the field-specifier call; parameter defaults and
  overloads do not change it (verified against pyright).
- **Keep `server_default=` and `default=MISSING`.** Rejected: the redundancy is
  load-bearing but reads as boilerplate, and the two-channel split is exactly what
  blocked a single-kwarg server-default declaration.
- **Markers passed to `default` (chosen).** One recognized channel for every kind
  of default; the marker carries the "computed by the database" meaning.

## Consequences

- **Breaking.** `server_default=` is removed from all constructors on both
  backends. Pre-1.0, no aliases -- consistent with ADR 0005's outright removals.
- `CurrentTimestamp` is now valid as a `default` value (reverses the previous
  prohibition).
- Future server-side defaults (literal or backend-specific) get a more flexible,
  type-sound home: distinguished marker objects passed to `default`, rather than a
  dedicated parameter. This is where the [ADR 0003](0003-per-backend-namespace-column-declarations.md)
  "backend-specific server_default" seam now lives.
- The Server Default concept (CONTEXT.md) is unchanged; only its declaration
  syntax moves.
