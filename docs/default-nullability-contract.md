# Defaults, nullability and migration: recommended contract

**2026-11-15 — #612 under #603. Recommendations awaiting maintainer decision,
not implemented behavior or permission to implement.**

The core declaration direction is already accepted in [PR #609](https://github.com/crpier/snekql/pull/609):
separate Python `default`/`default_factory` and SQL `server_default` parameters;
retain Col/GenCol, Pending/Row, the Row witness and explicit pending defaults.
Repeated `default=PENDING_GENERATION` is an accepted cost. Do not reopen it here.
The [static proof in draft PR #611](https://github.com/crpier/snekql/pull/611)
supports the three anchor forms on real Text declarations on both backends. It
proves neither runtime behavior nor the nullability/migration proposals below.

## Recommendations in brief

1. **Keep annotation-derived physical nullability when unspecified.** A field-level
   `T | None` implies nullable storage by default; `T` implies non-null storage.
   Explicit `nullable=` overrides that physical choice without rewriting Python types.
2. **Permit both explicit mismatches.** Non-null Python over nullable SQL is useful
   for brownfield mappings. Nullable Python over non-null SQL is also allowed, but
   validating a value does not promise that the database will accept a write.
3. **Treat SQL defaults as schema facts, not Python construction defaults.** Do not
   run them through application validators or silently serialize them as logical
   Python values. SQL DEFAULT NULL requires physically nullable storage, not a
   nullable application contract.
4. **Make one documented breaking cutover in a future 0.x minor release.** No dual
   old/new default semantics. Retain LiteralDefault only temporarily as a diagnostic
   token, not as an accepted recipe; move literals and clocks to `server_default`.

These choices minimize changes beyond the accepted separation while preserving
brownfield flexibility. They are recommendations, not four new recorded decisions.

## Status and scope

The shipped reference is snekql 0.9.0 at
`5f4dd8189c529a99713b629a71e60088c6974204`. Source and guides were inspected; no
new runtime models, checker probes, SQL or database tests were executed for this
contract. Existing [usage documentation](typing.md) still describes shipped behavior.

All snippets below are **proposed declaration excerpts**, inside the lifecycle-generic
class required by [ADR 0020](adr/0020-class-body-models-with-pending-and-row.md).
`db` means SQLite for these examples; the contract also targets MariaDB, subject to
its existing storage/identity restrictions. `server_default` is not currently supported.
No input/read generic split, checker plugin or generated constructor is introduced.

## 1. Five independent facts, without five new public options

A declaration answers different questions:

- **Presence:** may Python callers omit the constructor argument?
- **Values:** what does the declared Pydantic contract accept and return?
- **Read type:** what type can a successful parsed Row expose?
- **Storage:** may the physical column contain SQL NULL?
- **SQL omission:** what does the database do if an INSERT leaves the column out?

Keep the existing Col/GenCol and lifecycle scheme. Ordinary `Col[T]` exposes T in
Pending and Row. `GenCol[T]` exposes `T | PENDING_GENERATION` in Pending and T in
Row. This is not a promise that a generation source exists or that a write succeeds.

The annotation describes the declared logical contract, not every raw input a lax
Pydantic parser could accept. Explicit validators may deliberately handle inputs
outside the nominal annotation. Neither `nullable=` nor a SQL default adds hidden
preconversion or changes the logical contract.

## 2. Nullability rules

### Unspecified nullable keeps the current inference

```python
required: db.Col[str] = db.Text()
nullable_but_required: db.Col[str | None] = db.Text()
nullable_and_omittable: db.Col[str | None] = db.Text(default=None)
```

The first requires a string and declares TEXT NOT NULL. The second requires a
string or None and declares nullable TEXT. Only the third permits constructor
omission, supplying None. These statements assume plain annotations without
additional validators. Pending and Row value types follow the annotations.

Infer physical nullability from resolved field-level None membership, including
ordinary aliases/Annotated wrappers, not by executing validators or factories.
None nested inside `list[str | None]` does not make the list field nullable.
If the annotation cannot be resolved safely, require explicit physical nullability
or fail declaration rather than guess. This does not resolve JSON null versus SQL
NULL; JSON input/serialization grammar remains a separate #603 question.

Primary-key/identity restrictions remain in force: no nullable primary-key contract
or None-based implicit generation. Generated IDs use the pending marker. Backend
DDL/catalog peculiarities still need their existing backend-specific handling;
this proposal does not pretend that every SQLite primary-key form has identical
physical semantics.

### Explicit nullable describes SQL, not an assertion about Python

```python
# Existing nullable column; application wants only successful non-null reads.
name: db.Col[str] = db.Text(nullable=True)

# Application admits None, but the existing database requires a non-null value.
note: db.Col[str | None] = db.Text(nullable=False)
```

For `name`, omission and explicit None fail ordinary string construction validation.
A parsed read of actual SQL NULL fails that same plain string contract; it is not
an absent row or a successfully returned None. Successful Row values are str. An
explicit application validator could handle NULL differently; snekql must not do
that implicitly.

For `note`, omission is still rejected; explicit None is logically valid. If None
is written as SQL NULL, the database's NOT NULL constraint rejects it. Keep the
Row annotation `str | None`; do not silently narrow it to str from schema metadata.
This combination is rarely useful, but rejecting it would recouple contracts
without establishing any general guarantee that all validated values persist.
Do not add an extra per-write NULL checker or an automatic runtime warning.

**Both mismatches currently fail model declaration.** Allowing them is a proposed
change. It does not imply that schema verification should ignore actual SQL drift.

## 3. Omission, defaults and generation

- Only a Python `default` or `default_factory` permits constructor omission.
  They are mutually exclusive. Either can coexist with an independent SQL default.
- A defaultless field remains required, even if its type admits None, it is GenCol,
  it has a SQL default, or it has an identity setting.
- `default=PENDING_GENERATION` requires GenCol. It supplies a lifecycle marker,
  not an application value and not a SQL default. GenCol also permits explicit
  pending input without making omission optional.
- Validate explicit inputs, ordinary Python defaults and factory outputs through
  the declared Pydantic contract before exposing a typed Pending value. Factories
  run only for omitted input during construction, never during declaration,
  schema verification or DDL generation. Do not pre-evaluate them to discover types.
- A SQL fallback does not fill or overwrite a Pending object's value. INSERT omits
  pending fields; it binds concrete values, including accepted scalar None as SQL
  NULL. It never binds the pending sentinel or substitutes SQL defaults in Python.
- GenCol may map generation managed outside the declaration, such as a trigger.
  Do not demand a recorded server_default/identity merely to admit pending input.
  Missing or incompatible real generation can still fail at the database.
- Preserve complete/Row rules: complete requires all logical values and rejects
  pending markers; defaults do not certify persistence. INSERT does not mutate the
  original Pending object into Row. Read/RETURNING validation is not write rollback.

Concrete contrast cases:

```python
# Required Python string, even though SQL has a fallback for other writers.
external: db.Col[str] = db.Text(server_default="external")

# Omission supplies "draft", not "queued"; INSERT binds the concrete value.
state: db.Col[str] = db.Text(default="draft", server_default="queued")

# Same independence with a factory; its output is validated as a Python value.
fresh: db.Col[str] = db.Text(default_factory=make_state, server_default="queued")

# Omission supplies pending; SQL can supply "fallback". Explicit None writes NULL.
label: db.GenCol[str | None] = db.Text(
    default=db.PENDING_GENERATION, server_default="fallback"
)
```

For `label`, Pending exposes `str | None | PENDING_GENERATION`; Row exposes
`str | None`. A default of SQL NULL does not collapse omission and explicit None:
the final SQL values may coincide, but Pending values and INSERT column lists differ.
The UPDATE omission/assignment contract is unchanged: a SQL schema default is not
a new UPDATE assignment marker. Existing explicit CurrentTimestamp assignments
remain separate from default configuration.

## 4. SQL defaults have a separate, bounded contract

Omitted `server_default` means no declared SQL default. Explicit
`server_default=None` means SQL DEFAULT NULL. Keep an internal unset representation;
do not add another public sentinel or overload PENDING_GENERATION with this meaning.

```python
# SQL permits NULL; the application insists on strings and requires input.
name: db.Col[str] = db.Text(nullable=True, server_default=None)
```

Other writers may omit `name` and produce NULL. Ordinary application construction
requires a string and binds it; parsed reads of actual NULL fail the plain str
contract. Do not reject this declaration just because None is not a valid Python
construction value. That is the point of separating the contracts.

Recommended initial boundary:

- Keep literal defaults bounded to supported ordinary scalar mappings: integer/Boolean
  literals with Integer/Boolean storage, string literals with Text/LongText, and NULL
  with physically nullable, non-primary-key columns in those families. Preserve
  SQLite bool-on-Integer support and supported backend spellings. No arbitrary
  expressions, SQL functions, Decimal, JSON, binary or new temporal literals.
- Treat these literals as SQL configuration. Preserve safe quoting and the existing
  Boolean-to-SQL-literal rendering where appropriate. Do not apply application
  constraints, Python factories, custom serializers or logical-value encoders to
  reinterpret a schema default. A constrained string application can map an ordinary
  text SQL fallback that its own validator rejects; reading that value then fails.
- Reject unsupported kinds and contradictory configuration before I/O: both Python
  default options, a pending default on Col, SQL DEFAULT NULL with NOT NULL, nullable
  primary-key declarations, and conflicting explicit SQL-default/auto-increment
  configuration. These are bounded declaration checks, not a general storage validator.
- Retain CurrentTimestamp as the supported SQL clock marker, with existing compatible
  storage and UTC-meaning restrictions. It does not call a Python clock, create an
  implicit pending default or promise a driver representation accepted in strict mode.

This deliberately changes current server-literal handling: today it validates and
encodes the literal through the logical application contract at model binding.
Decoupling those paths needs new runtime evidence; #611 only added a parameter to
copied signatures and retained old overloads. Do not call the work implemented.
The existing NULL-plus-NOT-NULL rejection remains an intentional initial limit even
if a particular database permits such a self-conflicting schema declaration.

## 5. Declarations, DDL and verification must agree on physical facts

A Python default/factory alone declares **no SQL DEFAULT**. Explicit `nullable=`
controls the expected physical NULL permission; the annotation-derived value applies
only when no override is given. Scaffold and schema verification must consume the
same declared physical facts, not infer different policies independently.

Verification checks the live column against those physical expectations, not whether
every stored row satisfies application validators. A nullable SQL column mapped to
str should structurally match nullable storage, while an actual NULL can still fail
a read. Do not query all rows or run factories as part of structural verification.

Preserve matched/drift/unchecked distinctions. In particular, MariaDB may not expose
the difference between implicit NULL and explicit DEFAULT NULL; supported catalog
normalization must report its limit rather than manufacture clause-level certainty.
Unknown default expressions must not become verified matches merely because their
sample result might satisfy a Pydantic type.

Changing a Query Mapping grants no Migration Ownership and never alters a live table,
backfills data, rewrites migration history or repairs another writer. The historical
Python `default=False` versus independently declared SQL DEFAULT 0 mismatch remains
real: either explicitly map the SQL default or deliberately change the schema through
a reviewed migration. Do not silently equate Python omission with SQL omission.

## 6. Recommended compatibility cutover

The current [compatibility policy](compatibility.md) permits documented breaking
changes in a 0.x minor release. Recommend one such future cutover, not a warning
period that keeps two default interpretations working. No release/version change
is made by this document; the prospective 1.x notice rules are not being rewritten.

Migration recipes preserve behavior where it was previously supported:

```python
# Old SQL literal default: implicitly made constructor input omittable.
attempts: db.GenCol[int] = db.Integer(default=db.LiteralDefault(0))
# New: state the Python omission and SQL default separately.
attempts: db.GenCol[int] = db.Integer(default=db.PENDING_GENERATION, server_default=0)

# Old SQL clock default.
created: db.GenCol[db.UtcDatetime] = db.Text(default=db.CurrentTimestamp)
# New: preserve omission explicitly, retain the SQL clock.
created: db.GenCol[db.UtcDatetime] = db.Text(
    default=db.PENDING_GENERATION, server_default=db.CurrentTimestamp
)
```

These snippets compare before/after forms, not duplicate fields to copy into a class.
The same migration applies to old LiteralDefault(None), with explicit
`default=PENDING_GENERATION` and `server_default=None` on a nullable supported field.

- Plain `default=value`, `default_factory=callable` and explicit pending identity
  declarations keep their construction meanings. Do not infer SQL defaults from them.
- Keep Col/GenCol, lifecycle generics and the Row witness. Do not automatically turn
  a generated field into ordinary Col just because an explicit value was supplied.
- Reject old `default=LiteralDefault(...)` and `default=CurrentTimestamp` in the
  cutover release, before I/O, with a declaration diagnostic explaining the new SQL
  channel **and the explicit pending default needed to preserve omission**.
- For that initial cutover release only, retain the LiteralDefault export as a
  diagnostic-only token so old imports can reach an actionable declaration error.
  Accept it in neither default channel; no automatic lowering, compatibility mode
  or new usage recipe. Plan removal in a later 0.x minor with its own release note.
  CurrentTimestamp remains an active SQL marker and is not removed.
- Static checks must reject typed legacy uses where possible; runtime declaration
  rejection still covers dynamically supplied options. #611 does not prove this
  rejection because its overlay intentionally retained legacy overloads.
- Previously matching explicit nullable flags retain their physical meaning. Formerly
  rejected mismatches become available; omission still uses the same inference.
  Do not weaken their new behavior through a silent nullable/type reconciliation.

Applications should pin their old release, inventory marker uses and generated
fields, then update declarations and run typing/constructor/query/schema checks
before upgrading deployed writers. A mechanical declaration rewrite is insufficient
for custom validators/serializers that previously transformed SQL default literals:
compare the **old encoded SQL default** with the proposed literal explicitly.
For example, if an old text validator uppercased "draft", preserving the schema may
require `server_default="DRAFT"`, not a blind move of the original Python value.
Some old serializers can produce a wire-literal kind not expressible by the proposed
bounded replacement for that storage family. There is then **no guaranteed equivalent
rewrite**: stop the mechanical upgrade, retain the old pinned application release,
and separately review a schema or application change. Do not coerce the encoded
literal into an apparently equivalent kind or add an unreviewed raw-SQL escape hatch.

Where declared physical facts remain equivalent, no database migration should be
needed solely for the syntax change. Check the actual schema using the facts that
verification can establish, and record unchecked or ambiguous facts explicitly.
Verification success is not proof of clause-level equivalence: for example, MariaDB
may hide whether DEFAULT NULL was explicit. Seek separate evidence where available;
otherwise record the unresolved limitation and obtain a rollout decision rather
than promote it to a verified fact. New/different SQL facts require separately
reviewed migrations and deployment coordination with other writers. Do not edit previously applied migrations to satisfy
new declarations. Rolling back code does not undo a schema/data change.

## Acceptance examples for later implementation—not tests run here

At separately agreed test seams, later evidence must establish:

- Omitted nullable input without a Python default is rejected; default=None permits
  omission only when the declared value contract accepts the resulting value.
- Required SQL-defaulted Col and GenCol remain required. Explicit pending permits
  omission without leaking the marker into successful Row/scalar result types.
- Python defaults/factories and SQL defaults can differ. Only omitted construction
  calls the factory, and its result is validated; SQL configuration never calls it.
- Non-null logical/nullable physical mappings declare successfully and reject actual
  NULL on a plain-str parsed read; the reverse mapping retains its logical type and
  delegates an actual violating write to the database.
- Explicit None versus pending selects bound NULL versus an omitted INSERT column,
  including DEFAULT NULL; no SQL literal is fetched to fill the Pending object.
- DDL and verification agree on independent physical nullability/defaults, preserve
  backend limitations and never treat structural matching as valid-row certification.
- Supported old declarations either migrate with equivalent omission/read/SQL facts
  or fail with an actionable diagnostic. No legacy marker is silently reinterpreted
  as a Python value. Existing explicit clock assignments remain unchanged.

This is a proposed contract for maintainer approval, not authorization for those
implementation tests or code. JSON/serialization grammar, independent input/read
generics, integer/bool policy, structured Unparsed, SQLite Decimal and broader
verification tooling remain separate #603 work.

## Source basis

Current behavior was inspected in `snekql/model.py` (server-marker lowering and
nullability checks), `snekql/_server_defaults.py` (literal validation/lowering),
`snekql/storage.py` (field-level None/clock handling), backend schema declaration
and verification code, and the [typing guide's server-default section](typing.md#literal-server-defaults).
The [design checkpoint](design-checkpoint.md) records accepted value ownership,
brownfield separation, transaction semantics and the outstanding nullability choice.
It predates the subsequent declaration acceptance and static proof cited above.
