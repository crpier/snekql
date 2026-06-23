# Column constructors name storage primitives; codecs derive from the logical type

Status: **Accepted**, implemented on `feat/storage-primitive-codecs` (see #144).
SQLite collapses to four storage-primitive constructors, codecs derive from the
annotation, and MariaDB gains a native `Uuid`; the full suite (snektest, pyright,
ruff) is green. May still be reverted if the ergonomics do not hold up, but the
design questions below are settled.

Adding first-class UUID columns forced a prior question: what *is* a column type
in snekql? A column type bundles three independent axes —

- **storage class**: where the bytes live (SQLite `INTEGER` / `REAL` / `TEXT` /
  `BLOB`), consumed by schema DDL and the drift check (`sqlite_storage_class`);
- **codec**: how a Python value crosses the wire to and from that primitive,
  consumed by `Attr.encode` / `Attr.decode`;
- **logical type**: what Python type the value actually is, consumed by pydantic
  validation and supplied by the field annotation.

Today the **column-type name is the primary key** into that space: `DateTime()`
fixes all three axes at once, and the annotation (`Col[datetime]`) *redundantly
restates* the logical axis. Two sources of truth that can disagree
(`Col[int] = Boolean()`) is exactly why a declaration-time cross-check guard
exists (`check_column_storage_compatibility`). The redundancy and the guard are
both costs of letting the column-type name carry the logical axis.

## Decision

**A constructor names a native storage primitive of its backend; the logical
type's single source of truth is the field annotation; validation and
serialization are delegated wholesale to pydantic.**

The codec is no longer selected by a column-type name. It is a thin wire-shaping
layer keyed on the **storage class**, wrapping the annotation's pydantic
`TypeAdapter`:

```python
created_at: Order.Col[datetime]        = Text()   # TEXT  + pydantic datetime
epoch_at:   Order.Col[EpochDatetime]   = Integer() # INTEGER + a user pydantic type
enabled:    Order.Col[bool]            = Integer() # INTEGER + pydantic bool (0/1)
id:         Order.Col[uuid.UUID]       = Text()    # TEXT  + pydantic UUID (str)
payload:    Order.Col[Json[dict[str, int]]] = Text()  # pydantic.Json[T] marker
```

### The backends are asymmetric, on purpose

This is the load-bearing consequence. The two backends do **not** get the same
constructor set, because "native storage primitive" means different things:

- **SQLite has four storage classes**, so the SQLite namespace exposes exactly
  four constructors: `Integer`, `Real`, `Text`, `Blob`. `DateTime`, `Boolean`,
  and `Json` are **removed** — they were codecs over `TEXT`/`INTEGER`, and that
  behavior now lives in the (storage class, pydantic type) pair. A datetime is
  `Col[datetime] = Text()`; a bool is `Col[bool] = Integer()`; JSON is
  `Col[pydantic.Json[T]] = Text()`.
- **MariaDB has many native types**, so its namespace **keeps** `DateTime`,
  `Boolean`, and `Json` as constructors (they name `DATETIME(3)`, `BOOLEAN`,
  `JSON`) and **gains `Uuid`** (native `UUID`). Their meaning shifts from
  "logical-type constructor" to "native-storage-primitive constructor." Storing
  a datetime as an integer (`Col[...] = Integer()`) or a UUID as `BINARY(16)`
  (`Col[uuid.UUID] = Blob()`) remains available as an opt-in.

So the codec-derivation machinery is overwhelmingly a SQLite concern; MariaDB
mostly keeps native constructors and lets codec-storage be opt-in. This stays
within [ADR 0003](0003-per-backend-namespace-column-declarations.md)
(per-backend constructor surfaces) and
[ADR 0004](0004-dialect-blind-core-with-open-ast-dialect-expressions.md) (the
codec stays per-backend; the dialect-blind core names no backend).

### Validation and serialization are pydantic's job

The library stops owning logical semantics. Concretely:

- **No `AwareDatetime` injection.** snekql will no longer force timezone
  awareness. A user who wants it annotates `Col[AwareDatetime]`; the previous
  automatic UTC canonicalization on encode is dropped.
- **No `_STORAGE_LOGICAL_TYPE` table and no `check_column_storage_compatibility`
  guard.** Storage/logical compatibility is whatever pydantic can serialize into
  the storage class. An impossible pair fails at encode/decode, not at class
  creation. Users get the freedom to shoot themselves in the foot.
- **JSON uses `pydantic.Json[T]`**, not a snekql marker. The codec sniffs the
  pydantic `Json` marker out of the annotation's `Annotated` metadata.

### The codec, concretely

The new pydantic-driven codec governs **SQLite's primitive storage classes, the
`pydantic.Json[T]` marker path, and plain scalars on both backends**. The
**MariaDB native types `DateTime`, `Boolean`, and `Json` keep their existing
codecs untouched** — this is forced, not just conservative: a MariaDB `DATETIME`
column wants the wire form `"2026-01-02 03:04:05.678"` (space-separated, no `Z`),
which pydantic's json-mode (`...T...Z`) cannot produce. So those native types
stay on their proven strftime-text / `1`/`0` / `dump_json` codecs, and
`_BackendCodec` (with its datetime format fields) **survives** to carry that
per-backend difference. `storage_type_name` therefore remains a codec dispatch
key — for the MariaDB native `Boolean` / `DateTime` branches — in addition to
being the MariaDB schema-compilation key.

For everything the new codec does own, empirically (pydantic 2.x):

- **Strict on construct, lax on fetch.** Model construction validates user input
  strictly (a `datetime` field rejects a `str`). Fetch decoding validates
  laxly, because the driver hands back a primitive (`str`/`int`) that must
  coerce up to the logical type (`str -> datetime`, `1 -> bool`,
  `str -> UUID`) — strict mode rejects exactly these.
- **Encode default is `adapter.dump_python(value, mode="json")`** — datetime and
  UUID become bare strings, int/bool/float pass through — **except** two cases:
  - `bytes` (BLOB) raises in json-mode, so BLOB encodes with `mode="python"`
    and decode normalizes `memoryview`/`bytearray` to `bytes`;
  - the `pydantic.Json[T]` marker is detected from the annotation metadata; the
    marker is stripped for the validation adapter, and the column encodes with
    `dump_json().decode()` / decodes with `validate_json(text)` — the same path
    the MariaDB native `Json` column already uses.

## Considered Options

- **Keep the column-type name as the key (status quo).** Rejected: every new
  logical type sharing a storage class multiplies named constructors, the
  annotation/declaration redundancy persists, and the guard must enumerate each
  new mismatch.
- **Storage-primitive constructors, validation delegated to pydantic.** Chosen.
  One source of truth for the logical axis (the annotation), storage made an
  explicit user choice, and the library sheds logical semantics it was
  re-implementing on top of pydantic.
- **Drop logical types entirely; store only raw primitives.** Rejected: it would
  push datetime/bool/UUID/JSON handling back into user code. The pydantic
  `TypeAdapter` stays; only the *selection key* moves to the annotation.

## Consequences

- **Breaking, no aliases.** SQLite `DateTime`/`Boolean`/`Json` are removed
  outright (pre-1.0, no users). Major-version-worthy if this were released.
- **Errors move from declaration time to runtime.** Removing the guard means an
  incompatible (storage, logical) pair surfaces at first insert/fetch via a
  pydantic error, not at class creation. Accepted in exchange for a smaller,
  pydantic-delegated surface.
- **Timezone behavior changes.** Naive datetimes round-trip as naive; awareness
  is opt-in via the logical type. Previously snekql forced `...Z` UTC.
- **`like` / `not_like` gate on the logical `str` type**, not on TEXT storage, so
  `Col[uuid.UUID] = Text()` does not expose `like`.
- **Storage representation is a deliberate per-column choice** (`Col[datetime] =
  Text()` ISO vs a user epoch type in `Integer()`), new expressiveness at a
  small legibility cost: the assignment site names storage, the annotation names
  type.
- **MariaDB keeps `JsonAttr`** (the `json_extract_int` operator subtype),
  produced by its native `Json()` constructor — unaffected.
- **First beneficiary: UUID.** `Col[uuid.UUID]`, client-generated via
  `default_factory=uuid.uuid4` (PK known before insert — a plain `Col`, not
  `GenCol`), `Text()` on SQLite and native `Uuid()` on MariaDB. Version pinning
  (v4 / v7) stays in userland (`Annotated[uuid.UUID, Predicate(...)]` + chosen
  generator).

## Open Questions

- **All constructors expose `server_default`** with no compatibility checking; a
  nonsensical pairing (e.g. a text `CURRENT_TIMESTAMP` default on an integer
  column) is the user's responsibility. Whether any of the server-computed
  defaults warrant a guard is left open and currently answered "no." The
  `CurrentTimestamp`-requires-a-`DateTime`-column declaration check is dropped on
  SQLite (which no longer has a `DateTime` storage type); the structural rules
  (generated column, `MISSING` default) remain.

  **Resolved by [ADR 0007](0007-server-defaults-as-default-markers.md):** the
  `server_default` parameter is removed. A server default is now declared as a
  marker value of `default` (`default=CurrentTimestamp`), which the metaclass
  routes to the internal server default and an omittable `MISSING` construction
  default.
