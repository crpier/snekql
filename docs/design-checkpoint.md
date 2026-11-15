# Interface design checkpoint — 2026-11-08

**Status:** Current redesign record, maintained in **issue #603 and draft PR #609
only**. Repository-only design/research material, **not current usage instructions
or an implemented redesign**. Work in this redesign continues in that same pair;
do not create an issue/PR for each discussion, experiment or document.

This is the current checkpoint for the defaults/nullability discussion begun under
#473 and the subsequent query-value and static-operation investigations. It combines
the original project conversation with its continuation, rather than treating each
research PR as an independent design decision.

Read the [design brief](design-brief.md) for purpose and principles. Read this document
for the current direction, its reasons and remaining decisions. The
[research index](design-research-index.md) records evidence and draft-PR disposition
recommendations. The [evidence capsules](design-evidence/README.md) preserve concrete
scenarios, known prototype gaps and selected original executable fixtures. Existing usage guides and accepted ADRs still describe the shipped
contracts; this checkpoint does not silently amend them.

**Subsequent discussion:** #603 now tracks the continuing redesign. The
[declaration design sheet](declaration-design-sheet.md) compares the current form
with two alternatives following #606/#607's partial storage-typing experiment.
Its core recommendation—separate default channels, existing lifecycle/Row declarations
and explicit pending defaults—was accepted on 2026-11-15. The SQL-style nullability
default was subsequently accepted (D3). The full contract remains unfinished; other
proposals are not automatically decisions or implemented. The later
[split-default proof](../research/split_defaults_610/README.md) establishes bounded
static feasibility. The [consolidation record](design-evidence/redesign-consolidation-2026-11-15/README.md)
preserves the separately opened PRs/issues; they are not separate ongoing work streams.

## In one page

The purpose is trustworthy query results over databases whose schema, data and other
writers cannot simply be trusted. Readable SQL-shaped code and practical verification
matter more than declaration brevity. A coherent default path should work end to end,
with deliberate customization for brownfield applications.

The intended division is:

- **Static typing:** establish which query operations are supported, plus result
  shapes, ownership/scope and value domains where the checker can express them.
- **Pydantic:** own declared value parsing, validation and serialization. Prefer
  existing Python/Pydantic types and explicit validators over a parallel codec policy.
- **snekql:** own SQL execution, result structure, cardinality, join presence,
  transactions, resources, representation entry-point selection and safe diagnostics.
- **Database/driver:** retain their actual storage/conversion limits. A successful
  write is not a universal promise that no information changed.
- **Development tools and agent skills:** help users inspect and check mappings,
  contracts and schema facts; explain intentional differences instead of forcing
  declarations to match mechanically.

This is a target division, not a claim that today's implementation has those exact
boundaries. In particular, existing encoding checks and runtime query gates remain
until separately implemented replacements are reviewed.

## How to interpret the status labels

- **Decision:** the maintainer explicitly endorsed the direction in conversation.
  It is not necessarily implemented, and exact syntax may remain open.
- **Working direction:** favored or authorized for investigation, with material design
  questions still open. It must not be presented as an adopted public API.
- **Evidence:** a particular prototype or source inspection established a bounded fact.
  Passing a checker does not select an interface or prove native database behavior.
- **Open:** unresolved choice or missing proof.
- **Superseded:** an earlier proposal or recommendation that should not be revived as
  a requirement just because it remains in an old report.

## Decisions and working directions

### D1. Brownfield flexibility is essential — decision

snekql must accommodate other database writers and independently managed schemas.
Python construction policy and SQL omission policy may legitimately differ:

```text
Python default: False
SQL default:    True
```

The Python application supplies False; another writer omitting the column receives
True. This is not inherently an invalid combination. Likewise, a nullable column may
be mapped to a non-null application contract if reading an actual NULL fails.

Keep these questions distinct: constructor argument presence, accepted Python values,
successful read values, physical NULL permission and schema-management ownership.
Distinct concepts do not automatically justify a public flag or generic for each.

### D2. Defaults need a clearer design — direction selected; syntax open

The maintainer concluded that changing the current overloaded-default approach is
worthwhile. On 2026-11-15, after the [declaration comparison](declaration-design-sheet.md),
the maintainer accepted separate Python `default`/`default_factory` and SQL
`server_default` parameters on existing storage constructors, retaining `Col`,
`GenCol`, the explicit Row witness and explicit `default=PENDING_GENERATION` where
omission should leave a field pending. Repetition of the sentinel is an accepted
cost, not a blocker to solve through a wrapper or changed requiredness. Selector
and field-wrapper variants are not chosen directions. Remaining declaration
restrictions and the compatibility plan are unfinished; no implementation or merge
was authorized by this decision.

Also accepted on 2026-11-15: Python defaults/factory outputs go through the declared
application Pydantic contract; SQL defaults do not go through application validators
or serializers. A SQL fallback may lie outside the application's accepted values,
with an actual read then failing validation. Validate supported SQL-default forms and
quote literals safely, but do not recouple the contracts through logical validation.
This does not select new SQL functions/literal families or the migration cutover.

Preserve omission versus explicit NULL and truthful Pending/Row values. A field's
ability to hold a pending sentinel is different from whether the constructor permits
omission. Database generation also includes identities, not only SQL DEFAULT clauses.

The working separate-parameter prototype repeated `default=PENDING_GENERATION` for
ordinary server-supplied values. A later native-ty workaround removed that repetition,
but required a constructor-only `required=True` for SQL-defaulted fields that must
still require Python input. The maintainer rejected that trade-off **as a standalone
change with the rest of the API unchanged**. It is not a selected public keyword.

### D3. SQL-style nullability defaults, independent of Python — decision; unimplemented

On 2026-11-15 the maintainer selected the ordinary SQL default: a column permits NULL
when nullable is omitted. `nullable=False` explicitly requests NOT NULL;
`nullable=True` explicitly permits NULL, subject to primary-key/identity constraints.
Do not derive SQL nullability from T versus T | None, and do not require a nullable
argument on every column. This replaces both the original inference-preserving
recommendation and the later mandatory-argument suggestion.

Python annotations and Pydantic still own logical values and successful-read types.
A plain str contract may map nullable SQL and reject actual NULL on parsed reads.
Nullable storage does not permit Python constructor omission without a Python default
or factory. Existing main behavior still infers nullability from annotations and
rejects explicit mismatches; the new direction is not implemented.

See the [default/nullability contract](default-nullability-contract.md) for the accepted
rule, its NOT NULL migration implications and remaining recommendations. SQL-literal
restrictions, cutover mechanics and other compatibility details are not automatically
selected by this approval. No independent input/read generic scheme is selected.

### D4. Driver values go directly to the declared Pydantic contract — decision

The maintainer explicitly chose this boundary:

```text
Database driver → Pydantic → query result
```

No hidden snekql conversion should first turn integer 1 into True or UUID text into a
UUID merely to make a supposedly strict contract accept it. The driver itself may
already perform conversions; this direction does not promise access to raw wire bytes.

Pydantic types, Annotated metadata, validators and serializers own value semantics.
Use standard Python and existing Pydantic types first, even if their names are not
ideal database terminology. Add library-owned types only for a demonstrated gap.

Intentional contract-controlled parsing remains allowed: ordinary Pydantic `int` may
accept numeric text while StrictInt rejects it. This refines the original desire to
reject unexpected data: don't **conceal** a mismatch through a second implicit policy.

snekql may still need to select Python-versus-JSON input grammar or output format.
The precise JSON construction/read boundary remains open; this is not permission to
pre-decode JSON through an independent snekql value policy. Earlier read-adapter/context
sketches are experiments, not the chosen interpretation of D4.

### D5. Three whole-operation read modes — decision; spelling open

| Mode | Value handling | Intended result value type |
| --- | --- | --- |
| No parsing | Preserve driver values; don't establish the logical contract | `Unparsed[T]` |
| Declared parsing | Honor annotations and validators, equivalent to strict=None | `T` |
| Strict parsing | Apply strict=True; explicit validators still participate | `T` |

Declared parsing is the favored default, not a selected public argument spelling.
Start with whole-operation policy. Defer per-field overrides until a concrete need.
Do not introduce a fourth forced-lax mode that relaxes explicit StrictInt declarations.

Strict mode may reject ordinary storage representations; that is expected, not a
reason to insert hidden conversions. Neither normal nor strict parsing is unchecked.

### D6. Unparsed marks each result, without a runtime wrapper — decision

Preserve normal result structure; mark the logical contract as unestablished:

```text
one result:           Unparsed[T]
all results:          list[Unparsed[T]]
optional result:      Unparsed[T] | None
streamed batch:       list[Unparsed[T]]
```

The outer list and absence/cardinality facts are snekql guarantees. Wrap each complete
selected result, not every field and not the outer list. Don't replace it with Any or
an annotation that the checker treats as ordinary T. Pydantic SkipValidation[T] does
not supply this static distinction.

A zero-wrapper scalar proof works. It does **not** establish full model materialization
or later validation: raw values carry no runtime adapter or type argument, and a
parser must obtain the complete contract elsewhere. TypeAdapter(T) accepts arbitrary
input and either returns T or rejects it; it does not infer T from Unparsed[T].

Constructing normal structured results without semantic validation and revalidating
them later without trusting their class identity remain implementation questions.

### D7. Validation failures follow ordinary exception/transaction behavior — decision

- List fetch: an invalid row fails the call; no partial list is returned.
- Single fetch: invalid data is an error, not no-row or a valid NULL.
- Streaming: earlier batches remain delivered; don't deliver the failing batch, and
  close the failed stream.
- RETURNING: returned-value validation failure does not itself undo the write.
- Let an error escape a transaction/savepoint to roll it back. Catching it inside
  leaves commit/rollback responsibility with the application. No special forced
  rollback state is selected merely for a validation error.

Provide safe, useful context without fetched values/bindings by default. A consistent
snekql error carrying query/row/field context was proposed; exact error classes,
formatting and diagnostics implementation are not selected here.

### D8. Prefer value contracts and safe storage choices, not a second storage validator — decision

The maintainer agreed not to reproduce general database storage validation, and later
rejected adding a final-serialized-parameter checking layer as impractical. Replace
existing storage-aware value checks deliberately as part of the new design; don't
retain them solely because they already exist.

Prefer reusable Pydantic constraints, well-chosen supported mappings, documentation
and development-time checking. A valid application value or successful write does
not prove lossless persistence. Strict SQL modes and warning inspection are useful
but do not catch all rounding/truncation; no universal lossless-write mode is chosen.

Writes and comparisons should serialize consistently. Write-fit restrictions must
not silently quantize comparison thresholds: a value unsuitable for storage can still
be a legitimate search bound. Exact serialization-mode selection and binding policy
are not finalized.

### D9. SQLite exact-decimal mapping remains unresolved — open

Text can retain decimal digits but ordinary text ordering isn't numeric. Canonical
text can fix equality, not ranges, numeric MIN/MAX or arithmetic. Integer minor units
introduce scale/unit conventions, conversion and arithmetic limits. The maintainer
challenged offering two competing general recipes for one type; neither became the
selected SQLite default.

A single understandable supported path is desired. Backend-specific restrictions
must be honest; a Python Decimal annotation doesn't make SQLite NUMERIC exact.
Datetime text is a different case: consistent canonical UTC/civil forms can preserve
chronological/civil order, unlike ordinary decimal text.

Removing the operation-support problem through static restrictions could make a
text-based decimal mapping more attractive, but storage format, equality, capabilities
and public declarations still need a decision.

### D10. Statically reject unsupported query operations — working direction with proof

The maintainer endorsed extending static operation restrictions and identified **ty
as the only intended supported checker**. Experimental ty features aren't a blocker
merely because the library itself is experimental.

The bounded proof in #602 shows ty 0.0.84 can exclude nominal ZonedDatetime from direct
ordering/range/extrema calls while retaining ordinary class-body declarations and
selected exact query/result types. Intersection/Not plus the existing value witness
is more promising than equating Python __lt__ support with database order safety.

This does not yet prove general **type-plus-storage capabilities**. Decimal text and
native DECIMAL share a Python value type but support different SQL operations. An
implementation must carry supported operations through projections, helpers, column
comparisons, aggregates and derived expressions, not merely block a few methods.

Removing duplicate runtime **operation-support** gates is a reasonable goal once the
supported typed surface is covered. This is distinct from runtime Pydantic checking
of actual values and driver/database errors. No runtime gates were removed by the
proof, and static checking does not certify dynamically supplied code or data.

### D11. Agent skills are part of practical verification — working direction

The maintainer proposed consumer-agent skills that check application contracts against
column declarations and, where authorized, actual schema facts. For example, explain
that three accepted decimal places may be rounded by a two-place column.

Differences are not automatically defects: stricter application contracts and deliberate
serializers can be legitimate. Skills should use evidence and explain consequences,
not mechanically rewrite declarations. A deterministic inspection tool feeding the
skill is an assistant proposal, not yet a selected or implemented tool.

Development-time checking complements runtime data validation; it is not proof that all
future writes preserve their inputs. No new consumer skill was authored in this work.

## What the prototypes establish—and do not

| Evidence | Established | Not established |
| --- | --- | --- |
| Defaults/nullability static research (#539, #583) | Tested constructor omission/value types and invalid controls; some useful short forms and some gaps | Selected declarations or native behavior |
| Current result audit (#592) | Existing paths apply different decoding/validation policies | A consistent new read policy |
| Strictness research (#594) | Source/upstream-test evidence of strict=None/True/False behavior and precedence | Local executed matrix, final operation API or backend bypass |
| Unparsed scalar proof (#595) | Static marker without runtime wrapper; explicit TypeAdapter output has target type | Generic type recovery, complete raw rows or model revalidation |
| Attribute/read research (#597, #598) | Selected synthetic representations and Pydantic composition/JSON/context behavior | Adoption of ReadInput, phase flags or all backend representations |
| Precision probes (#600) | Existing decimal constraints, a datetime validator and serializer gaps in 30 focused cases | Universal fitting checks or exact SQLite numeric storage |
| Static-ordering proof (#602) | Call-site errors for tested Zoned ordering while positive controls pass | Complete capability propagation or every query path |

These are historical executed/source-inspection results at recorded versions. They are
not fresh reruns or evidence that today's production code implements the target.
See the [research index](design-research-index.md) for reproducible/pinned references.

## Superseded or explicitly not selected

- Generated constructor signatures and the annotation-left/Python, right/SQL split:
  abandoned after native typing and ergonomic concerns.
- Prefixed constructors and outer wrappers: researched but not front-runners; don't
  revive them solely because static prototypes passed.
- Rejecting independent Python/SQL defaults as inherently nonsensical: superseded by
  the brownfield requirement.
- Keeping the current defaults API as the conservative recommendation: superseded by
  the maintainer's conclusion that a change is worthwhile, not by a finalized API.
- Best-effort snekql decoding before Pydantic: superseded by the direct-driver boundary.
- SkipValidation or Annotated metadata alone as unchecked typing: insufficient.
- Per-field Unparsed runtime containers: superseded by whole-result, static-only marking.
- ReadInput helpers or global SQL-read phase flags as selected interfaces: never selected;
  later direct-driver decisions constrain what remains acceptable.
- Additional final-parameter checks as the precision solution: rejected as a new layer.
  Their prototypes remain evidence of a serializer gap, not a proposed production hook.
- Two SQLite decimal recipes as the settled recommended user experience: challenged,
  not adopted. Existing shipped guidance is a separate compatibility fact.
- Python comparability as a general database operation-capability test: insufficient.
- Multi-checker portability as a requirement for the new design: not a requirement;
  ty-specific maintenance and runtime annotation handling still need care.

## What happens next

1. Continue the redesign in issue #603 and draft PR #609 only. The older nine drafts
   were archived in merged #604; later separately opened tasks/PRs are preserved in
   the current consolidation record, not competing specifications or work queues.
2. Review the remaining default/nullability compatibility proposals in the current
   contract. The separate-default direction, explicit pending cost and ordinary
   SQL nullable default are settled; do not redo those decisions or the completed
   declaration/construction typing proof.
3. Keep the completed Decimal capability experiment's limits visible: propagation
   was conditional, declaration claims were unsound and ordinary integer operations
   regressed. It is not a completed sound capability system. Do not expand that
   overlay or remove runtime guards without a separately agreed scope.
4. Close the remaining value-handling boundaries with one representative workflow:
   construction, serialization, driver→Pydantic reads, JSON and Unparsed structured
   results. Reuse full declared constraints; no hidden competing conversion layer.
5. Only then scope an implementation slice, compatibility changes, consumer guidance
   and agent checks. Native behavior tests are required before claiming backend/storage
   guarantees. Keep migration implementation separate.

This is a short dependency order, not authorization to implement every item or reopen
all abandoned designs. Under the maintainer's subsequent explicit authorization, the
nine related research drafts were closed without merging after complete artifact
preservation in #604. The [inventory](design-research-index.md) records that retirement.
The separate migration implementation PR remains open; no runtime changes were made.
