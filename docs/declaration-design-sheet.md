# Model declarations: caller-facing design sheet

**2026-11-15 — core direction accepted; full contract unfinished and unimplemented.
Not a current usage guide.**

Tracks #608 under #603. This follows the merged [design checkpoint](design-checkpoint.md)
and the partial storage-typing experiment in [draft PR #607](https://github.com/crpier/snekql/pull/607).
No new typing proof, model execution or database tests were performed for this sheet.

## Accepted direction

**Use separate Python `default`/`default_factory` and SQL `server_default`
parameters on the existing storage constructors. Keep `Col`, `GenCol`, the explicit
Row witness and explicit pending defaults for now.** The maintainer accepted this
core recommendation (alternative A below), including its repeated sentinel cost:

> yeah I agree with the recommendations; I'm ok with eating the cost of declaring db.PENDING_GENERATION often

This records a design decision, not permission to implement or merge, or a claim
that the complete contract already works. Remaining nullability details and the
compatibility plan are not settled by that acceptance.

That is an intentionally limited decision. It makes default ownership clear
and supports independent application/schema policies without a wrapper on every
field. It does **not** hide the repeated pending sentinel or solve static storage
capabilities. Make those costs visible rather than sell a shorter declaration that
changes required-input behavior or relies on an unapproved exception flag.

Do not add a separate operation-capability argument beside storage. Keep runtime
operation checks where static coverage is missing. If eliminating them would make
normal declarations worse, elimination is not worth that price.

## What is decided, proposed and evidenced

- **Maintainer decisions/direction:** Python/schema policies can differ; Pydantic owns
  value interpretation; defaults need a clearer interface; only ty needs support.
  The core separate-parameter direction and explicit pending cost are now accepted.
  The full interface and its implementation are not finalized.
- **Current implementation:** described below at `5f4dd8189c529a99713b629a71e60088c6974204`,
  using the [model guide](models.md), [typing reference](typing.md) and source inspection.
  Existing hidden value conversions are not endorsed by showing current declarations.
- **Remaining proposal:** the physical-nullability override described below is
  still comparison material; the final nullability rules are not selected here.
  Alternative B remains an unselected comparison, not a second supported recipe.
- **Historical evidence:** narrow defaults prototypes exist, and #607 demonstrated
  conditional propagation of a storage marker through a CTE. Neither proves these
  complete proposed declarations, their runtime behavior or a sound capability model.

All examples retain the single-model lifecycle from
[ADR 0020](adr/0020-class-body-models-with-pending-and-row.md). A Query Mapping does
not grant Migration Ownership: none of these declarations changes a live table.

## Same cases, three forms

`db` below means `snekql.sqlite`. Imports such as `UUID`, `uuid4` and `ClassVar`
are ordinary Python imports. These are declaration excerpts, not standalone scripts.
There are exactly two alternatives; storage and nullability sections apply the same
forms rather than introduce more candidates.

### Current form — implemented reference

```python
class Job[S = db.Pending](db.Model[S]):
    __row_type__: ClassVar[db.ReadType[Job[db.Row]]]

    title: db.Col[str] = db.Text()
    state: db.Col[str] = db.Text(default="draft")
    token: db.Col[UUID] = db.Text(default_factory=uuid4)
    remote_state: db.GenCol[str] = db.Text(default=db.LiteralDefault("queued"))
    id: db.GenCol[int] = db.Integer(
        primary_key=True, auto_increment=True, default=db.PENDING_GENERATION
    )
    note: db.Col[str | None] = db.Text()
```

`default` means either a Python default or a SQL default, depending on the value
passed. `LiteralDefault(...)` and `CurrentTimestamp` are SQL markers; ordinary
values and factories are Python behavior. Identity generation is a separate fact.

The reference is compact and implemented, but the reader must recognize markers
to know where a default runs. The original `default=False` versus SQL `DEFAULT 0`
misunderstanding was correctly caught by verification; it was not a verification bug.
The [checkpoint](design-checkpoint.md#d2-defaults-need-a-clearer-design--direction-selected-syntax-open)
records why improving this is considered worthwhile.

### Alternative A — accepted direction: separate named defaults, same declaration seam

**Hypothetical replacement parameters; do not copy into current applications.**

```python
class Job[S = db.Pending](db.Model[S]):
    __row_type__: ClassVar[db.ReadType[Job[db.Row]]]

    title: db.Col[str] = db.Text()
    state: db.Col[str] = db.Text(default="draft")
    token: db.Col[UUID] = db.Text(default_factory=uuid4)
    remote_state: db.GenCol[str] = db.Text(
        default=db.PENDING_GENERATION, server_default="queued"
    )
    id: db.GenCol[int] = db.Integer(
        primary_key=True, auto_increment=True, default=db.PENDING_GENERATION
    )
    note: db.Col[str | None] = db.Text()
```

The reader has one rule: `default`/`default_factory` are Python; `server_default`
is SQL. A SQL default alone does not make the Python argument optional. The pending
sentinel is a Python initial state, not a SQL default value. Omitted `server_default`
means no declared SQL default; explicit `server_default=None` means SQL DEFAULT NULL,
not a Python default of None. `default` and `default_factory` remain mutually
exclusive; either may coexist with an independent SQL default. This does not propose
arbitrary SQL expressions or broaden the supported literal-default value families.

This is the conservative separate-parameter shape already explored historically.
The proposed larger change is independent schema policy, not a claim that a new
parameter by itself resolves the whole defaults/nullability discussion.

### Alternative B — one field wrapper, storage nested inside

**Hypothetical `db.field` helper and SQL parameter, neither currently exported.**
Every field uses the wrapper in this candidate; it is not a second optional recipe
for the same declaration.

```python
class Job[S = db.Pending](db.Model[S]):
    __row_type__: ClassVar[db.ReadType[Job[db.Row]]]

    title: db.Col[str] = db.field(db.Text())
    state: db.Col[str] = db.field(db.Text(), default="draft")
    token: db.Col[UUID] = db.field(db.Text(), default_factory=uuid4)
    remote_state: db.GenCol[str] = db.field(
        db.Text(server_default="queued"), default=db.PENDING_GENERATION
    )
    id: db.GenCol[int] = db.field(
        db.Integer(primary_key=True, auto_increment=True),
        default=db.PENDING_GENERATION,
    )
    note: db.Col[str | None] = db.field(db.Text())
```

Python construction policy belongs to the outer field; physical storage/schema
options belong to the inner constructor. This could concentrate default-handling
implementation in one module instead of repeating it across storage constructors.
It is not the abandoned annotation-metadata/generated-signature split: there is no
left-hand `Default(...)` metadata or generated constructor. Nevertheless its native
ty field-specifier behavior and integration are **unproved**.

It adds nesting to every field, retains the pending repetition and does not recover
storage information erased by `Col[T]`. Those costs outweigh its potential internal
locality benefit on current evidence. **Do not advance B over A merely to move
implementation plumbing behind a new public helper.**

## Exact behavior to preserve across the examples

These are existing reference behaviors and intended candidate behaviors, not new
executed results. Explicit inputs must satisfy the declared Pydantic contract.
`Pending` below describes an ordinary constructed `Job`; successful whole-model
reads produce `Job[Row]`.

- **Required `title`:** omission is rejected; explicit string is accepted and
  `None` rejected. Pending and Row expose `str`. The column is SQLite TEXT NOT NULL
  with no SQL default; INSERT supplies the explicit string.
- **Python-defaulted `state`:** omission supplies `"draft"`; an explicit string
  overrides it and `None` is rejected. Pending and Row expose `str`. SQL storage is
  TEXT NOT NULL with **no SQL default**; Python supplies the value on INSERT.
- **Python factory `token`:** omission calls `uuid4` for that construction; explicit
  UUID overrides it and `None` is rejected. Pending and Row expose `UUID`. Storage
  is TEXT NOT NULL without a SQL default. This sheet does not select new serializer
  or strict-read behavior for UUID text; the broader Pydantic redesign still applies.
- **Server-defaulted `remote_state`:** omission supplies `PENDING_GENERATION`, not
  `"queued"`. Explicit string overrides the SQL fallback; `None` is rejected.
  Pending exposes `str | PENDING_GENERATION`; Row exposes `str`. Storage is TEXT
  NOT NULL with SQL `DEFAULT 'queued'`. INSERT omits the pending field, while explicit
  values are bound. Current form gets this from `LiteralDefault`; A/B make the
  Python omission default explicit.
- **Generated `id`:** omission supplies `PENDING_GENERATION`; explicit integer is
  allowed subject to the actual backend's identity rules, and `None` is rejected.
  Pending exposes `int | PENDING_GENERATION`; Row exposes `int`. SQLite storage is
  INTEGER PRIMARY KEY AUTOINCREMENT, **not a SQL DEFAULT**. Pending is omitted on
  INSERT. An insert does not mutate the Pending object into a Row.
- **Nullable-but-required `note`:** omission is rejected; callers supply string or
  `None`. Pending and Row expose `str | None`. Storage is nullable TEXT with no SQL
  default. Explicit `None` is SQL NULL, never a request to use a server default.
  Adding a **Python** `default=None` makes it omittable; nullability alone does not.

The shared Row type does not certify persistence or a successful write; `complete`
can also produce a complete snapshot. Keep the explicit Row witness rather than
assume a decorator or runtime inference can provide the checker's exact result type.

## Brownfield contrast cases: where the change earns its cost

### Independent defaults

Both are intended to be valid in A:

```python
# Required in Python; SQL fallback is for writers that omit this column.
external_state: db.Col[str] = db.Text(server_default="external")

# Python omission supplies one value; SQL omission by another writer another.
state: db.Col[str] = db.Text(default="draft", server_default="queued")
```

In B, the same policies are `db.field(db.Text(server_default="external"))` and
`db.field(db.Text(server_default="queued"), default="draft")` respectively.
Factories can coexist with SQL defaults on the same principle. Current public
server-default declarations require `GenCol` and prohibit a Python factory, so
these independent combinations are not expressible by the current default form.
Do not imply that the current implementation supports them.

For both contrast fields, Pending and successful Row values are `str`; neither
holds a pending marker. The first rejects constructor omission; the second accepts
it and supplies `"draft"`. Both reject `None`, bind concrete values on ordinary
INSERT and declare TEXT NOT NULL with their specified SQL default. SQL omission
only matters when a writer actually omits the column.

### Nullable server defaults: omission still differs from explicit NULL

The current form can express this with
`db.GenCol[str | None] = db.Text(default=db.LiteralDefault("fallback"))`.
The intended A spelling is:

```python
label: db.GenCol[str | None] = db.Text(
    default=db.PENDING_GENERATION, server_default="fallback"
)
```

B puts `db.Text(server_default="fallback")` inside
`db.field(..., default=db.PENDING_GENERATION)`. In every form, constructor omission
holds the pending sentinel and INSERT omits the column, allowing SQL to supply
`"fallback"`. An explicit string overrides it; explicit `None` is bound as SQL NULL,
not replaced by the fallback. Pending exposes `str | None | PENDING_GENERATION`;
successful Row values expose `str | None`. Storage is nullable TEXT with the stated
SQL default.

Changing the SQL default to NULL preserves that distinction. Current syntax uses
`default=db.LiteralDefault(None)`; A uses `default=db.PENDING_GENERATION,
server_default=None`; B moves those settings into the respective storage/field
calls. Omission and explicit None may then produce the same final SQL value, but
their Pending values and INSERT column lists still differ. None is not a substitute
for the omission marker.

### Existing database clocks stay in the SQL channel

The intended A spelling for the existing supported clock marker is:

```python
created: db.GenCol[db.UtcDatetime] = db.Text(
    default=db.PENDING_GENERATION, server_default=db.CurrentTimestamp
)
```

Current form uses `default=db.CurrentTimestamp`; B uses
`db.field(db.Text(server_default=db.CurrentTimestamp), default=db.PENDING_GENERATION)`.
Omission stays pending, explicit compatible timestamps override, and a successful
Row exposes the declared timestamp type. Keep the existing supported clock/storage
combinations and SQL-default semantics; no arbitrary SQL function interface,
new precision/timezone guarantee or implicit conversion is proposed. The full
Pydantic-read integration remains a separate redesign question. The new spelling
and runtime lowering are intended, not newly tested behavior.

### Physical NULL permission is not the application's accepted value set

A proposed A declaration for an existing nullable column:

```python
name: db.Col[str] = db.Text(nullable=True)
```

B puts the same storage declaration inside `db.field(...)`. Intended behavior:
Python construction requires a string; `None` is rejected. Successful parsed Row
values are `str`. SQL storage permits NULL; actually reading NULL fails the
non-null application contract rather than producing a falsely typed result.
There is no default and no implicit omission. **Current snekql rejects this
annotation/flag mismatch.** This is a proposed change, grounded in the agreed
brownfield requirement, not existing support.

For the common examples, this sheet retains today's annotation-derived physical
nullability when `nullable=` is absent. That keeps the comparison controlled; it
does not select the final SQL-nullability default. Proposed explicit `nullable=`
would describe a physical fact rather than merely assert agreement with Python.

The reverse case—Python accepts `None`, SQL forbids it—must not be silently narrowed
into a different input type. A contract may validate a value that the database
rejects. Whether to permit that declaration or diagnose it as a development concern
remains open; no duplicate general write-validation layer is proposed here.
A schema-only SQL DEFAULT NULL may likewise serve other writers while a stricter
application always supplies a non-null value. Do not automatically validate every
SQL fallback as if it were an application's Python construction default.

## Decimal: same Python value, storage declared once

The following uses **existing mappings as comparison examples**, not a newly
selected SQLite recommendation. Native and canonical-text values are both Python
`Decimal`; Annotated canonicalization metadata is not a new nominal Python class.

Current form and A use the same declarations (in their respective backend models):

```python
amount: mariadb.Col[Decimal] = mariadb.Decimal(12, 2)
amount: sqlite.Col[sqlite.CanonicalDecimal] = sqlite.Text()
```

B adds only its field wrapper:

```python
amount: mariadb.Col[Decimal] = mariadb.field(mariadb.Decimal(12, 2))
amount: sqlite.Col[sqlite.CanonicalDecimal] = sqlite.field(sqlite.Text())
```

All four examples require an input, reject `None`, expose `Decimal` in Pending and
successful Row results, and declare non-null storage without a default. Native
MariaDB storage is DECIMAL(12,2); SQLite is canonical decimal TEXT. This says
nothing about universal precision preservation or strict-mode acceptance of text.

Native storage has numeric SQL equality/ordering/aggregation semantics; canonical
text can support equality/membership but not ordinary numeric ordering or arithmetic.
That is a storage-semantic distinction, **not a claim that every native Decimal
operator is implemented**. In particular #607 recorded that current binary `.add()`
overloads do not support Decimal even on native storage.

None of the three forms makes `ty` recover the RHS storage choice from the existing
`Col[Decimal]` descriptor. B does not fix that by wrapping the RHS. The #607
experiment propagated an **explicit** extra marker through a CTE but allowed false
class-body claims and introduced regressions. Do not copy that marker into these
forms or promise static rejection they cannot establish. Retain runtime operation
checks and honest documentation unless a separately reviewed design proves more.

This still leaves one understandable SQLite decimal path to choose in the broader
redesign. The comparison is not an offer of two interchangeable SQLite recipes.

## Why A, and what it still costs

- **Readability:** A names Python versus SQL defaults at the existing declaration
  seam. Current syntax hides the distinction in marker knowledge. B makes the
  split structural, but ordinary fields become noisier.
- **Repetition:** A retains one declaration of logical type and one of storage;
  there is no separate capability claim. It repeats the pending sentinel for
  omittable generated fields. B repeats the same sentinel and adds a wrapper.
- **Leverage and locality:** the declaration module should hide lifecycle/default
  lowering and stable metadata publication, not require callers to manage them.
  B might centralize implementation, but internal organization alone does not
  justify a wider interface. A can still share implementation internally.
- **Typing:** A has bounded historical evidence for separate defaults with explicit
  pending, not complete evidence for the proposed nullability policy or constructor
  parity. B has no verified advantage. Both need eventual imported-consumer,
  required-input, wrong-value, Pending/Row and query-result controls.
- **Compatibility:** A keeps bare `default=value` Python-side, rather than silently
  turning existing code into SQL defaults. It still changes server-default and
  nullability policy and needs an explicit migration plan. B also rewrites every
  field. Neither changes a database just because a model changes.

Dependencies stay familiar: in-process Pydantic for values and ordinary metadata/
lifecycle logic; ty as the external checker; actual SQL engines and drivers for
storage and execution. No new adapter registry, generated typing files or checker
plugin is introduced by this recommendation. SQL verification and migration
readiness remain separate concerns.

## Deliberate non-decisions and the next step

This recommendation does not revive the abandoned left/right typing generator,
server-prefix families or selector menus. Nor does it adopt the historical
`required=True` omission workaround. That technique removed common pending defaults
but moved an extra constructor-policy flag to the required-input SQL-default case;
the maintainer rejected that trade-off as a standalone change. Experimental ty
features are acceptable, but do not make an unwanted caller contract desirable.

A defaultless `GenCol[T]` remains required while admitting explicit pending input.
Do not make every `GenCol` optional merely to shorten the generated-ID example.
Do not remove ADR 0020's lifecycle parameter or Row witness without replacement
proof. Separate input/read generics, strict integer/bool policy, structured Unparsed
and JSON entry-point selection are still #603 questions, not silently solved here.

**The explicit-pending trade-off is settled:** the maintainer accepts clearer default
ownership and brownfield independence at the cost of repeating
`default=db.PENDING_GENERATION` where needed. Do not keep treating removal of that
repetition as a blocker, add a wrapper merely to hide it, or reintroduce `required=True`.
That does not settle every nullability or compatibility detail or complete the redesign.

The next proposed step is to scope one new proof at the declaration and constructor
seam, confirming its exact tests before writing them. It should check the hardest independent-default/omission case
and exact Pending/Row types, including negative controls—not expand the #607 overlay.
No such proof or implementation is authorized or performed by this design sheet.

## Evidence and validation limits

The historical [shortlist comparison](design-evidence/pr-snapshots/539/research/defaults_473/shortlist-comparison.md.txt)
and [callable-intersection report](design-evidence/pr-snapshots/539/research/defaults_473/callable-intersections.md.txt)
are archived research, not current usage instructions. The
[left/right report](design-evidence/pr-snapshots/539/research/defaults_473/left-python-right-sql.md.txt)
records why that generated route was abandoned. The current nullability/default
observations were checked against `snekql/model.py` declaration validation and the
typing guide at the baseline revision above. #607 remains separate research; it
was not merged into this document's branch or rerun here.

This work changes documentation only. Static repository/style and local-link checks
validate the edit, not the hypothetical examples' typing, runtime, SQL or usability.
