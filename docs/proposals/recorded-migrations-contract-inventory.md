# Recorded migration contract inventory (#477)

Status: **engineering audit / proposed hardening scope, not a release contract**.
Audited implementation: `1a69b5c` on the experimental PR #482 branch.
See [prototype status](recorded-migrations-prototype.md) for execution and recovery.
Follow-up in this PR now implements bounded generated-default verification,
pre-effect refusal of unsupported defaults/CHECK expressions, and a separate-process
native deployment/recovery route. The historical four-failure audit below remains
evidence for `1a69b5c`; it is not the current outcome of those cases.
This document does not change runtime behavior, publish a supported-version promise,
or supersede the existing migration ADRs. User-guide work remains deferred.

The [supported-scope proposal](recorded-migrations-supported-scope.md) now consolidates the
workflow milestones into a finite candidate contract and promotion gates. It recommends strict
SQLite adoption, explicit writer exclusion, execution epochs including target preparation,
versioned original-plan persistence and runtime deadline/session integration. This historical
inventory is evidence, not a requirement to implement every listed parser/resource opportunity
before a bounded release. The proposal is not approval or newly demonstrated support.

The [prepared-evidence follow-through](recorded-migrations-prepared-evidence-review.md) adds
bounded versioned original-plan persistence and explicit execution-epoch admission on new
plans, with actual replacement-worker/deferred-rebuild/native-restart use. Nested package
validation/current lowering checks remain: this does not solve standalone compiler-epoch
compatibility or change historical package identities, adoption authority or readiness scope.

The later [execution-epoch checkpoint](recorded-migrations-execution-epoch-review.md) now
separates defined epoch-one canonical replay and target lowering from public current authoring.
It preserves legacy bytes and live safety gates; an actual changed grouping candidate is
refused rather than silently replacing historical interpretation. This is one supported legacy
interpreter, not a general future compiler/codec/dependency ABI or automatic conversion.

The later [bounded I/O deadline checkpoint](recorded-migrations-io-deadline-review.md) implements
checked-out/control/cleanup budgets and interrupted-target disposal without treating SQLite
awaiter timeout as rollback or physical stop. Actual native original-plan recovery is retained;
connection opening/acquisition, session/durability and remaining outcome policy stay open.

The later [native-opening checkpoint](recorded-migrations-native-opening-review.md) adds a
native acquisition deadline and shares owned partial-connection/mandatory-TLS admission with
ordinary pool filling. It observes actual TCP EOF/cancellation and frozen-role/current-app use
over verified TLS; SQLite opening, coordination acquisition and remaining G3 policy stay open.

The later [SQLite physical-opening checkpoint](recorded-migrations-sqlite-opening-review.md)
adds a separate acquisition budget and retained explicit cleanup for eventual late handles.
Actual Linux leases expose continued worker waits after caller timeout/cancellation; physical
worker/FD observations precede fresh frozen-role/current-app use. Guard/coordination acquisition,
session/durability and outcome/shutdown policy remain open; no journal or replay policy change.

The later [local target-guard checkpoint](recorded-migrations-local-guard-review.md) bounds
queued caller acquisition without discarding another operation's active session or timing its
whole body. Actual native role work survives queued expiry/cancellation and completes on the
same target. Server coordination acquisition and remaining session/durability/outcome/shutdown
policy remain open; no new public facade or complete G3 claim.

The [native coordination checkpoint](recorded-migrations-native-coordination-review.md)
retains fractional server waits and distinguishes known refusal/reusable target from unsafe
interrupted GET_LOCK I/O. Real grant/refusal/deadline/cancellation leaves the active role owner
intact and retains original evidence/current typed use. Server wait is not a new client-wide
acquisition clock; SQLite coordination and other G3 session/durability/outcome/shutdown policy
remain open.

## Objective and evidence rules

The first production proposal should cover a deliberately bounded set of physical
facts emitted by the existing model compiler. It should not require understanding
arbitrary SQL, and it must not silently treat an unverified fact as verified.
Model/query use must remain independent of migration ownership.

The inventory follows the actual experimental call chain, not the separate
released `Database.verify` implementation:

- `migrations.generate` uses `build_schema_plan`, backend column compilation,
  `compile_create_table_sql`, and `compile_create_index_sql`.
- `ColumnState` records name, definition, nullability, storage and optional historical
  query annotation. `TableState` records columns, construction SQL and listed index
  SQL. These are not a durable Python codec contract.
- `prepare_steps` validates bounded native declarations. SQLite completion uses
  `validate_managed`; native completion uses `_mariadb_presence_obstacle` and its
  subordinate checks. Recovery reuses native endpoint checks when it can collect
  usable observations and otherwise satisfy recovery prerequisites.
- `Package.load` recompiles the draft for consistency/integrity. This is not a
  general semantic proof that every SQL fragment agrees with every recorded field.

**Compared** below means the implementation compares the stated fact, within the
listed limits. It does not mean full SQL equivalence or that every possible form
has a dedicated test. **Unclaimed** means there is no corresponding endpoint proof;
it does not mean the declaration is rejected. **Rejected** identifies a supported
refusal, which can happen before execution or after irreversible native effects.
The original source audit is not itself passing-suite evidence; follow-up runtime
changes have separate public-seam tests.

## Generated physical facts

| Model/compiler input | Recorded/generated form | SQLite endpoint | MariaDB endpoint |
| --- | --- | --- | --- |
| Table and column names | `TableState`, `ColumnState`, quoted DDL | Recorded table presence and declaration token comparison | Base-table resolution and physical-column namespace binding; no `_rowid` alias shortcut |
| Storage family and parameters | Backend column definition | Declaration tokens, not the released verifier's affinity-only comparison | Bounded native storage signatures, lengths/precision/signedness and known aliases |
| Nullable/required | Column flag and DDL | Declaration comparison; separate row/precondition checks for contraction | Exact native nullability in both directions |
| Single/composite primary key | Inline or table-level primary-key DDL | Declaration comparison | Ordered full ascending native primary key; ordinary unique indexes are not a substitute |
| Automatic integer identity | AUTOINCREMENT / AUTO_INCREMENT | Declaration, preserved rebuild sequence high-water and identity checks | Attribute identity compared; changing counter values are intentionally not schema drift |
| Text collation | SQLite non-BINARY override; native utf8mb4 charset plus collation | Recorded declaration comparison | Supported explicit utf8mb4 collation, plus implicit JSON collation; arbitrary charset-only claims unclaimed |
| No SQL default marker | No DEFAULT clause; ordinary Python defaults/factories do not become schema defaults | Recorded declaration tokens | Bounded absence compared: nullable omission accepts effective NULL; required absence excludes a native DEFAULT clause. Not a guarantee of omitted-write behavior |
| `LiteralDefault(None)` | `DEFAULT NULL` on a supported nullable non-key column | Recorded declaration tokens | Compared against NULL native metadata; implicit nullable NULL accepted; not proof of explicit clause spelling |
| Integer / Boolean `LiteralDefault` | Decimal integer SQL; Boolean encoded as 0/1 | Recorded declaration tokens | Compared through bounded quoted native default definitions; Boolean wire values are 0/1 |
| Text `LiteralDefault` | SQLite quoted text or hex CAST; native UTF-8 hex CONVERT expression | Recorded declaration tokens | Compared through supported UTF-8 hex CONVERT/literal forms; string identity preserved |
| `CurrentTimestamp` | Backend clock expression for supported destination storage | Recorded expression tokens; not clock/value semantics | Compiler DATETIME/text clock forms compared; unsupported expressions rejected; no clock/timezone/value proof |
| Column `unique` / `index` | Separate named CREATE [UNIQUE] INDEX, not inline UNIQUE | Listed index declaration signatures | Listed index name, uniqueness, ordered native-bound members, exact prefixes, ascending BTREE and non-ignored state |
| Table-level indexes | Same listed index route; SQLite predicate / native prefix options | Predicate included in signature; no general expression equivalence | Supported full/prefix column members compared; unsupported expression/direction/index-option forms rejected |
| Scalar/table foreign keys | Ordered table-level relationships and declared actions | Declaration tokens; separate rebuild foreign-key check | Relationship members/target/actions/multiplicity compared; parent must resolve to an observed InnoDB base table |
| Named `CheckConstraint` | Named CHECK with bounded local predicate syntax | Recorded declaration tokens | Finite compiler expressions, declared names and multiplicity compared; unsupported expressions rejected; bounded JSON validity remains separate |
| JSON storage | Backend storage declaration; MariaDB JSON alias | Recorded storage declaration, not application JSON shape | LONGTEXT storage, required collation and bounded JSON_VALID constraint shape; no stored-data or application-codec audit |
| Table storage | Generated SQLite STRICT / native ENGINE=InnoDB | Table suffix comparison | Explicit engine identity compared; missing/hidden identity cannot certify it |

The literal-default authoring surface is already bounded by
`_server_defaults.bind_literal_default`: ordinary integer, Boolean and text
storage; typed values; supported nullable NULL; no auto-increment combination.
The encoded wire value can differ from its logical Python value. Native text
emission is `(CONVERT(X'...' USING utf8mb4))`. A verifier designed only around
`DEFAULT 'text'` would therefore miss the compiler's normal output.

Clock emission also has more than one form. Native DateTime uses
`CURRENT_TIMESTAMP(precision)`; supported text destinations use a CONCAT/REPLACE
expression. Both now receive a dedicated default check. They are not covered by the separate
**ON UPDATE** check; ON UPDATE and DEFAULT remain different physical claims.

The CHECK compiler emits comparisons, IS [NOT] NULL, NOT, IN/NOT IN, BETWEEN,
AND/OR, and encoded literals. Supporting this finite generated language is a
smaller objective than arbitrary SQL predicate equivalence. Definition presence
and equivalence would still not prove that application sessions enforce checks.

## Edited construction and native-only forms

Some existing native checks cover reviewed construction SQL beyond what the
ordinary model compiler emits. Their existence must not inflate the generated
surface's coverage:

| Form/fact | Current limit |
| --- | --- |
| Virtual/stored generation | Kind compared; expression equivalence and generated values unclaimed |
| INVISIBLE | Visibility compared; not a general write-behavior proof |
| ON UPDATE CURRENT_TIMESTAMP | Bounded temporal precision compared; other functions/expressions rejected by that parser |
| Inline UNIQUE or unlisted indexes | Not covered by the listed-secondary-index proof; generated `unique=True` uses a listed index instead |
| Arbitrary defaults, comments and table options | Unsupported explicit default expressions now rejected; no general comment/table-option equivalence proof or full attribute-grammar claim |
| Foreign-key reference compatibility | Parent availability and engine identity compared; no independent referenced-column/index/type compatibility proof |
| Malformed base-table catalog SQL | Explicit PackageError, including the known MariaDB 12.2.2 escaped-FK rendering; not guessed repair |

MariaDB rejection after DDL preserves committed effects and uncertainty. Unreadable
catalog SQL can prevent recovery inspection entirely; it does not necessarily
produce an `ambiguous` Recovery object. For readable observations, other recovery
prerequisites can still block finish/retry/reconciliation.

## What the audit demonstrated natively

Four temporary negative tests used the approved generation, compilation,
preparation and application seams on an isolated owned native server. Each started
with a model-generated draft, retained its `ColumnState` default declaration, and
intentionally changed the table's construction SQL:

| Recorded column claim | Construction substitution | Observed result at `1a69b5c` |
| --- | --- | --- |
| Integer DEFAULT 7 | DEFAULT 8 | `applied`, phase `complete` |
| Boolean DEFAULT 1 | DEFAULT 0 | `applied`, phase `complete` |
| Text UTF-8 CONVERT default for `seed` | DEFAULT 'other' | `applied`, phase `complete` |
| DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6) | Default removed | `applied`, phase `complete` |

All four tests expected PackageError and failed because no exception was raised.
These are **open-gap evidence, not passing validation or new committed regression
tests**. They show that the native endpoint guard does not enforce these recorded
column defaults, not that unmodified `generate` emits incorrect SQL. They also
expose an authoring consideration: construction SQL and column declarations are
separate representations; compilation does not generally prove their semantic
agreement. SQLite's endpoint comparison instead follows recorded table SQL, so
these native probes are not evidence of an equivalent SQLite default-value gap.

Evidence is retained locally in `.snektest/477-contract-inventory/`, including the
probe source and completed four-failure report. The initial probe used an invalid
plain datetime annotation; its collection failure is excluded. Corrected probes
use UtcDatetime. The temporary test module was removed; no deliberately failing
suite or changed runtime behavior is committed by this audit.

## Ownership, route, observation and readiness are separate

- Defining a model is not ownership. Passing it to generation selects desired
  managed scope; whole-table relinquishment removes a claim without deleting data.
- Creation support is not alteration support. `_changes` accepts only routes
  representable by current operations. SQLite default-only alteration now has a
  structured operation and strict endpoint declaration checks, including removal.
  SQLite generation also composes nullable-to-required enforcement with a default
  transition, refusing old NULLs unless an explicit earlier backfill fixes them.
  Bounded native default alteration now uses targeted SET/DROP DEFAULT; combined
  required/default changes use the existing MODIFY route and NULL preconditions.
  Nullable defaulted additions now require explicit `defaulted_additions="leave_null"`:
  add without a default, then set the future-write default. Required additions and
  implicit fill-with-default policies remain unsupported. Named whole-column index
  additions use format 5; explicit bounded index removal/replacement now uses
  format 6. Named table CHECK additions use format 7; explicit bounded removal/replacement
  uses format 8. Inline changes and arbitrary reordering remain unsupported.
- SQLite adoption is intentionally stricter than normal endpoint checks: exact
  bounded declarations/indexes/storage and additional guards, rather than the
  managed-subset check used when preserving unmanaged additions. MariaDB adoption
  remains rejected.
- Managed scope is not uniform rejection of every extra object. SQLite managed
  validation permits extra declaration parts; native physical-column presence and
  listed-index checks do not reject all extra columns/indexes. Native foreign-key
  comparison, in contrast, includes unexpected relationships. Decide the intended
  negative claims explicitly; do not advertise full schema equality.
- Whole-catalog drift detection binds execution to accepted observations. It does
  not turn an unverified endpoint fact into a verified one.
- SQLite copied-value/identity checks protect the supported rebuild route. Native
  transactional UPDATE receipts and structural reconciliation address different
  guarantees; neither establishes general application-data correctness.
- Completion is not application readiness, privilege sufficiency, session-policy
  enforcement, codec compatibility, arbitrary expression equivalence or power-loss
  durability. Historical contracts do not freeze arbitrary Python codecs.
- The released `Database.verify`/TableShape implementation is a separate interface.
  Its existing literal-default or CHECK support cannot be credited to this runner
  without an explicit, tested integration that preserves model-free deployment.

## Proposed order of remaining work

This is the working engineering order, not a promise that every current experimental
form will be production-supported:

1. **Finish each implementation revision's CI.** The known malformed-rendering case must exercise
   explicit refusal, while ordinary/valid escaped-name routes continue to pass.
   A green refusal test does not make the affected schema executable on 12.2.2.
2. **Harden the implemented generated-default proof.** Integer/Boolean constants,
   generated UTF-8 text and compiler clock forms now have bounded checks.
   Use native negatives and positives through preparation/application/recovery;
   do not evaluate arbitrary default expressions or reuse model-dependent runtime
   verification wholesale. Unsupported forms must have an explicit policy.
   Native absence now excludes hidden scalar/clock defaults; nullable omission
   accepts native NULL without claiming explicit clause spelling. Required absence
   does not promise omission failure under every session mode or identity policy.
   Native set/change/remove defaults now execute, including required composition,
   preserved values, model-free deployment/relinquishment and acknowledged recovery.
   Nullable defaulted additions have an explicit leave-NULL policy, tested with
   scalar/text/NULL/clocks, SQLite preservation/rollback and native partial progress.
   Native ADD/default steps are separate; writes in between can receive NULL.
   Required-to-nullable relaxation now uses bounded AllowNull (format 4), preserving
   values and composing with defaults. Coupled constraints/comments require adapters;
   SQLite rollback and native partial-proof refusal are covered. Lost relaxation
   receipts remain ambiguous; the require/drop projection cannot ignore that fact.
   Lost default receipts remain ambiguous: require/drop-only reconciliation cannot
   certify ignored defaults. Old completed receipts are not retrospectively certified.
3. **Harden the implemented compiler-language CHECK proof.** Finite expressions,
   names and multiplicity now receive endpoint checks; unsupported forms remain
   rejected before effects. Known NOT/association/singleton-IN renderings normalize,
   not arbitrary equivalence. Redundant column CHECK claims must agree with table
   construction. Expression token/parenthesis/tree limits are implemented, not
   general package/database resource limits. Definition still does not prove
   session enforcement or existing data correctness.
4. **Reconcile the claim inventory with preparation.** Decide what is authoritative
   when reviewed construction SQL and recorded column fields differ. Every proposed
   initial physical claim needs a proof or an explicit pre-effect refusal; adding
   one rejection must not silently bless unrelated unclaimed attributes. No new
   public adapter/coverage API or artifact format is prescribed by this audit.
5. **Expand whole-route and deployment-evolution coverage.** One new subprocess
   route covers create/add/backfill/contract, transactional recovery and native
   relinquishment without importing models. Remaining hardening includes combining
   SQLite adoption/relinquishment/re-adoption routes, additional native interruption
   windows, package/compiler compatibility, coordination and resource limits.
   The reader now bounds wire bytes, JSON nesting and structural units, rejects
   duplicate keys and requires explicit integer versions/operation kinds. Three
   fixed prior-writer packages (including contraction) deploy with stable
   identities. Format 3 carries `ChangeDefault`; format 2 refuses that operation
   and its new metadata. Unchanged old routes keep their format and digests; an
   isolated preceding reader refuses format 3. Model-free default changes,
   preservation and atomic rollback/retry now have public route coverage. A second
   fixed chain from writer `7932c4f` preserves an explicitly authored format-3
   required/default composition while current generation learns to derive it;
   existing NULLs block it, and an explicit typed-backfill route is covered.
   Native transitions now use the same operation vocabulary; an actual `a650a3b`
   reader explicitly refuses them rather than silently executing unsupported work.
   New defaulted-addition generation uses the existing AddColumn/ChangeDefault
   vocabulary: an actual `9795442` reader loads both backend artifacts unchanged
   and deploys SQLite without authoring models. No new format or ledger conversion.
   Compilation now separately limits SQL to 1 MiB per source and 4 MiB aggregate,
   including repeated input, emitted SQL and frozen contraction SQL; output is
   charged incrementally. An actual older oversized artifact is explicitly refused,
   without changing normal artifact identities. Parameters, operation counts,
   parser work, catalogs, prepared SQL, IO/deadlines and total memory remain outside
   that byte envelope. This is input-decoding coverage, not whole-program resource bounds,
   general compiler compatibility or ledger evolution; no automatic conversion
   or retrospective recertification is available. Broader native
   adoption, arbitrary SQL equivalence, multiple heads, implicit stamping and
   cross-system orchestration are not prerequisites for this bounded proposal.

All runtime changes still require TDD at the approved public seams. Do not add
long-lived characterization tests asserting false completion as desired behavior.
The initial release scope, production integration and release decision remain open.

## Source map

Paths are relative to the repository root; function names identify the audited
implementation without relying on unstable line numbers.

- `snekql/experimental/migrations.py`: state records, `generate`, `Package.load`,
  `_changes`, `_contract_table`.
- `snekql/_schema_plan.py`: `PlannedModel`, `_column_indexes`, foreign-key planning.
- `snekql/_schema_compile.py`: CREATE TABLE/index and CHECK/FK construction.
- `snekql/sqlite/_schema_ddl.py`, `snekql/mariadb/schema.py`: backend column DDL and
  table suffixes. Their expected-shape/runtime verification paths are not the
  experimental runner's endpoint proof.
- `snekql/defaults.py`, `snekql/_server_defaults.py`, backend `_dialect_sql.py`:
  allowed markers, encoded literals and clock SQL.
- `snekql/_checks.py`: bounded predicate rendering.
- `snekql/experimental/_migration_prepare.py`: preparation, declaration signatures,
  managed-subset validation, exact adoption and rebuild preparation.
- `snekql/experimental/_migration_mariadb.py`: bounded native declaration parsing.
- `snekql/experimental/_migration_target.py`: native observation, physical name
  binding, endpoint checks, history and execution/recovery.
- `tests/experimental/test_migration_targets.py` and
  `tests/experimental/test_migration_contraction.py`: existing public-seam native
  and SQLite behaviors; not a claim that every source-audit row is fully tested.

### Relaxation format boundary

Format 4 adds `allow_null` and `relaxed` metadata. Formats 2/3 refuse both, including
empty new metadata; older operation sets retain their existing formats and digests.
An actual archived `5b2b891` reader refuses the new backend artifacts. A separate
SQLite process deploys the frozen route without authoring models. This does not
establish general compiler/codec compatibility, a ledger upgrade, or all interruption
windows. Broader index variants, broader CHECK forms and the audit queue remain open.

### Named index creation checkpoint

Format 5 adds CreateIndex for appended unconditional, quoted, whole-column indexes
on managed tables, unique or nonunique. Existing recorded index declarations must
also fit the bounded grammar; expressions/prefixes/directions/predicates/options,
comments and IF NOT EXISTS require adapters. No inferred deletion, replacement,
reordering or physical-index adoption. Source/emitted SQL uses the existing byte
budgets; this is not a total-work/index-size/identifier/catalog/IO budget.

Public routes cover duplicate-data SQLite rollback/correction/retry, index-before-
rebuild with unmanaged object/value preservation, native missing-index drift,
acknowledged CREATE followed by resumable data failure, and ambiguous lost CREATE
receipts. A counterfactual emitting nonunique SQL for a unique claim fails endpoint
verification after native effects; it does not complete. Archived c27bf4d refuses
format 5; current reader keeps prior format-4 artifacts and fixed format-2/3 fixture
identities. Model-free SQLite deployment enforces uniqueness. No ledger conversion.

Explicit bounded index removal/replacement now has negative postconditions below;
named CHECK additions and explicit removal/replacement are covered below. Construction/claim authority, unexpected-object ownership boundaries,
FK referenced-column/index/type proof, broader workflow/recovery/resource/evolution
coverage remain unfinished. Guides/release-scope/API reconciliation are deferred.

### Explicit index deletion checkpoint

Format 6 adds DropIndex, resolved by exact managed name rather than inferred from
absence. Bounded replacement is DROP plus CREATE; surviving-then-new declaration
ordering still limits automatic generation. Unowned/implicit/primary indexes and
unsupported index forms are not newly authorized.

Negative endpoint checks supplement positive managed-subset checks. They run before
SQLite commit and native completion/recovery finish, with same-name replacements
proved positively. SQLite DROP projection prevents a later rebuild resurrecting the
removed index. Counterfactual skipped DROP formerly completed; it now refuses on both
engines and cannot finish native recovery. Unrelated native prefix indexes retain
their own verifier grammar rather than being forced through the deletion grammar.

Pre-effect conservative dependency checks include observed SQL, before/target and
intermediate table sources—even a created then relinquished child. SQLite FK and
INDEXED BY dependencies refuse; native FK checking must remain enabled and opaque
visible application triggers/routines refuse. Checks are not a global dependency,
privilege or session-enforcement proof. Construction SQL remains trusted executable
input, not a sandbox or fully proven construction/claim agreement.

SQLite failed replacement restores the old index/rows/receipt; native failed CREATE
retains acknowledged DROP and permits CREATE-only retry after explicit data correction.
Lost DROP receipt remains ambiguous, with no automatic repair/structural acceptance.
Native replacement has an application-visible gap and no write-pause guarantee.

An archived 6c15088 reader refuses format 6; preceding format4/5 artifacts and fixed
format2/3 identities remain unchanged. Model-free SQLite deployment preserves values
and permits duplicates after explicit removal. No ledger conversion. CHECK changes,
general construction/claim/negative-ownership/FK compatibility, combined workflows,
resource limits and genuine compiler/codec/ledger evolution remain unfinished.

### Named CHECK addition checkpoint

Format 7 introduces AddCheck and added_checks metadata for appended named table
constraints. Reuse the finite general CHECK expression/work envelope, managed-column
binding and SQL-byte limits; repeated frozen CHECK metadata is charged independently.
No arbitrary functions/SQL equivalence, removal/replacement/inline rewrite or JSON
alias exemption expansion. SQLite observed constraint-name collisions refuse before
effects, including preservation mode; recorded name collisions refuse compilation.

Native checking-disabled RED exposed false completion over invalid existing rows.
The new route now requires enabled engine checking at preparation/application,
completion and recovery without silently setting session policy. This is not a
future application-session guarantee, general row audit or retrospective certificate
for legacy/initial CHECK declarations.

SQLite invalid-data and later-DML failures roll back rebuild/receipt, preserve
unmanaged objects/values without firing insert triggers, and allow corrected retry.
Native failed ALTER can retry after explicit correction when evidence permits;
acknowledged CHECK is not replayed after data failure. Lost receipts remain ambiguous,
with no new structural reconciliation. Native effects are not rolled back as a package.

Archived 10863c4 refuses format7; format4/5/6 artifacts and fixed format2/3 identities
remain unchanged. Model-free SQLite deployment preserves rows/default and rejects an
invalid insert. No ledger conversion. CHECK removal/replacement is covered below; remaining work includes the
remaining construction/claim/negative-ownership/FK compatibility, workflow/interruption,
resource and genuine compiler/codec/ledger evolution work. Guides remain deferred.

### Explicit CHECK removal/replacement checkpoint

DropCheck requires an exact uniquely recorded bounded named table CHECK. Generation
leaves destructive decisions unresolved; resolution precedes dependent changes.
No inline/unnamed/JSON-alias/unowned removal, and no arbitrary reordering. SQLite
rebuild retains other constraints/unmanaged objects/values/defaults, never resurrects
the rule during later relaxation, and rolls back failed same-name replacement. Explicit
data correction permits retry; no copy-time insert trigger execution.

Native DROP CONSTRAINT can resolve an implicit FK sharing the CHECK name! A genuine
owned-server probe removed that FK and left the CHECK. New catalog authority gates
refuse ambiguous existing names at preparation and recheck exactly one native CHECK
before every DROP. Intermediate CREATEs may remain committed when their generated
names cannot be verified; the unsafe DROP is not issued and recovery refuses that
next step. Tests learn actual implicit names. This is not general privilege-visibility,
construction/claim, dependency or FK type/index compatibility proof.

Native acknowledged DROP/failed ADD leaves a gap, with corrected ADD-only retry.
Lost receipts stay ambiguous; no new structural reconciliation/automatic repair.
Explicit negative endpoint proof survives relinquishment and checks physical owner
availability. Same-name managed replacements use positive proof. Skipped-DROP
counterfactuals exposed false completion after relinquishment on both engines; guarded
SQLite rolls back and native uncertainty/finish refusal remain.

Format8 adds drop_check/removed_checks; formats2–7 refuse vocabulary/empty metadata.
Archived84574ce refuses artifacts; format4/5/6/7 identities and fixed format2/3 fixtures
remain. Model-free SQLite2→7→8 preserves42/default7 and allows-1. Removal/relinquishment/
readoption (SQLite) and native relinquishment routes are covered. No ledger conversion.
Broader points1–4 remain incomplete; guides deferred.

### Identifier binding checkpoint

Compiler/load-time binding now requires one complete quoted table identifier exactly
matching its recorded name, and each column definition's first identifier must match
its separate name. Empty/duplicate/ASCII-case-colliding recorded names refuse rather
than being silently collapsed. Before/target snapshots, intermediate CREATE/ADOPT
(including subsequent relinquishment), ADD COLUMN and ChangeDefault payloads are
checked. SQL tails/comments/string/bare-name quoted_name fragments refuse.

Actual archived3456c05 writer/reader accepted a mismatched quoted_name artifact;
current loading explicitly refuses it while preserving the valid companion dump and
preceding format2–8 identities. Fixed fixtures preserve these bytes. Isolated-copy
counterfactual bypass reproduces acceptance without mutating working source. No new
format/ledger/receipt conversion or publisher authentication.

This closes identifier-representation gaps, **not** overall construction/claim
agreement. Table SQL header, redundant column coverage/physical storage/nullability/
defaults, broader namespaces/Unicode/native-case policies, indexes/constraints,
privilege visibility and unexpected-object/negative-ownership/FK compatibility still
need independent proof/refusal. Trusted construction SQL is not sandboxed. The
remaining workflow/interruption/resource/compiler/codec/ledger queue stays open.

### Construction header authority checkpoint

Compile/load now admits only unqualified ordinary CREATE TABLE naming the exact
recorded owner, across before/target and intermediate CREATE/ADOPT even after later
relinquishment. Keyword case/whitespace and properly quoted identifier contents are
preserved, not substring-matched. Views, TEMP/VIRTUAL, IF NOT EXISTS, schema-qualified,
AS/LIKE and commented headers require an explicit adapter. Does not broaden adoption
or infer permission to claim an existing object.

Earlier native wrong-owner/view routes left committed effects before endpoint refusal;
now they refuse pre-execution with no objects/history. SQLite wrong-owner similarly
refuses before execution. Endpoint guards unchanged; those old probes were **not**
false-completion evidence. Actual archived2b596f5 compiler/reader accepted wrong-owner
format2; fixed fixture now explicitly refuses, valid companion retains bytes/digest.
Model-free deploy id42, no authoring imports. Isolated-copy gate bypass reproduces
acceptance without mutating working sources. No new format/ledger/receipt conversion.

Header spelling is exact; native catalog/lower-case-table-names resolution remains
independent. No body/all-effects/column coverage/storage/nullability/default/index/
constraint agreement, Unicode/native namespace, privilege, unexpected-object/drift or
FK compatibility certificate. Trusted SQL is not sandboxed. Broader claim authority,
workflow/interruption/resource/compiler/codec/ledger queue and points1–4 remain open.

### Positive managed-column coverage checkpoint

Compile/load now requires exactly one actual column declaration per recorded managed
column, across before/target and intermediate CREATE/ADOPT even after relinquishment.
Names in CHECKs/constraints/expressions/strings/comments and query pseudo-aliases do
not supply physical declarations. Duplicate/ASCII-case-colliding managed declarations
refuse. Order/ASCII case can differ; quoted keyword contents remain identifiers,
SQLite distinct Unicode is not conflated. Single-quoted column spellings require an
adapter. This is bounded positive presence, not arbitrary native namespace equivalence.

**Genuine SQLite false completion:** actual archived86f6ab1 compiled/read/applied a
package recording id/value while construction SQL created only id. Phase complete,
PRAGMA table_info only id. Existing endpoint followed table SQL rather than contrary
ColumnState. Fixed old artifact now explicitly refuses compile/load/preparation;
in-memory typed packages cannot bypass revalidation. Native missing-column/_rowid
cases move from late committed-effects refusal to preconstruction/no history. Legacy
native setup independently preserves evidence that _rowid queryability is not a
physical declaration. Runtime endpoint guards unchanged.

Extra construction columns are not manufactured ColumnState claims: they do not grant
DropColumn authority. Existing table-SQL/backend endpoint claims still apply, so extra
SQL is not universally unclaimed/unowned. Reordered/case-variant positive routes on
both engines preserve value/default7 and extra default9. No new format/vocabulary or
ledger/receipt conversion; actual old valid format2 dump retained and deploys model-free
id42/default7. Gate bypass in isolated copied source reproduces SQLite false completion
without mutating working sources. Fixed2/3 and preceding backend2/7/8 identities remain.
Already-completed historical receipts are not automatically repaired/revoked; status
reports history rather than retrospectively certifying an old schema.

Storage/nullability/default agreement and broader constraint/index/namespace/privilege/
unexpected-object/negative-ownership/drift/FK compatibility, combined workflows/
interruption/resource/compiler/codec/ledger queue remain open. Points1–4 incomplete;
trusted SQL not sandboxed, draft/guides deferred, no production-readiness assertion.

### Ordinary nullability-claim checkpoint

Compile/load checks ordinary nullable flags against their column definitions and
construction declarations, bidirectionally. Top-level NOT NULL vs explicit/implicit
NULL; excludes DEFAULT NULL, parenthesized expression/CHECK/quoted tokens. Multiple
clauses refuse. Before/target and intermediate CREATE/ADOPT checked despite later
relinquishment; ADD/default payload flags independently bind before projection.

Key members excluded from this **ordinary** proof (inline or potential table-level).
This does not certify primary-key nullability across table/backend modes; existing key
checks remain independent. Constraint names do not exempt unrelated ordinary columns.
Both-engine table-key/ordinary-nullable positives retain explicit NULL/default7.
CHECK/default effects may still reject NULL independently of declared nullability.

Actual archivedadb59a6 SQLite completed a package claiming required metadata/definition
but constructing a nullable column, then accepted NULL. Fixed format2 artifact now
refuses at compile/load/prepare, including typed Package shortcuts. Opposing native
nullability mismatches now preeffect/no history rather than late committed-effects
refusal; runtime endpoint guards unchanged. Isolated copied-source gate bypass again
falsely completes/accepts NULL, no mutation of working source during native suites.
Valid companion literal digest/dump/model-free id42/default7 retained, prior backend2/7/8
and fixed2/3 identities unchanged. No new format/ledger/receipt conversion, historical
receipt revocation/repair or publisher authentication. Status remains history.

Storage/default agreement, full key/constraint/index/native namespace/privilege/
unexpected-object/negative-ownership/drift/FK and workflow/resource/compiler/codec/ledger
queue remain open. No general SQL/all-effects/sandbox/production certificate; points1–4
incomplete, draft/guides deferred. Existing default-edit restrictions and CHECK-removal
scope tests remain, with consistent fixtures/precise earlier nullability diagnostics.

### Physical definition/construction storage checkpoint

Compile/load checks physical definition types against matched construction declarations,
before/target/intermediate CREATE/ADOPT even after relinquishment. ADD/default prefixes
admitted independently, so unsupported claimed intermediate types cannot hide behind
empty final target. Positive managed claims only; extras do not manufacture ColumnState
claims and existing SQL/backend endpoint comparisons still apply.

SQLite finite INT/INTEGER/REAL/TEXT/BLOB/ANY, keyword-case normalization only; no affinity
collapse. INT/INTEGER distinction protects type identity needed for rowid reasoning, not
all key semantics. Parameters/multiword modifiers/unknown type names adapter. All six
positive spellings execute/retain precise values. Native bounded aliases/implicit params/
integer display widths normalize, significant size/precision/signedness remain. JSON→
LONGTEXT is storage only, not validity/collation/codec proof. Unknown claimed/constructed
types/modifiers now fail compilation, including intermediate ENUM/relinquishment; earlier
unsupported declaration preparation refusals move earlier, not become supported.

Actual archived5c4a655 SQLite completed INTEGER definition/TEXT constructor and accepted
'not integer' as text. Fixed artifact now explicitly refuses load/typed preparation.
Native family/size/precision/signedness/unknown-constructor cases now pre-DDL/no history
instead of late committed-effects refusal; those native cases were not false completion.
Runtime catalog/postcondition guards unchanged. Isolated copied-source bypass again
false-completes SQLite; working source unmutated during native suites. Valid old literal
dump/digest/model-free id42/default7 retained, backend2/7/8/fixed2/3 identities remain.
No format/ledger/receipt conversion or retrospective revocation/repair/authentication.

Not coarse ColumnState.storage-hint/Python codec/query annotation certification, complete
attribute/default/tail equivalence, key/index/constraint/namespace/privilege/negative-
ownership/drift/FK or all-effects/sandbox proof. Native family-to-codec guessing is not
an adapter. Remaining claim/default/workflow/interruption/resource/compiler/codec/ledger
queue stays open; points1–4 incomplete, draft/guides deferred.


### Bounded default declaration/construction checkpoint

Compile/load binds each managed frozen default to its construction declaration,
including absence, before/target/intermediate CREATE/ADOPT despite relinquishment.
Standalone ADD/ChangeDefault terms remain admitted independently of final ownership.
Positive managed claims only; extra declarations do not manufacture claims and existing
SQL/backend endpoint guards remain independent. Equal unknown expression bytes cannot
certify a default.

SQLite finite integer/Boolean/text/NULL literals (including generated UTF-8 hex CAST),
cosmetic wrappers and compiler TEXT clock expression; whole terms, not scalar prefixes.
Literal identity is preserved; keyword case is not blanket string/clock-format folding.
Absence differs from explicit NULL. Arithmetic/arbitrary functions/floats/other unknown
terms require an adapter even when both sides match. No SQL evaluation. Native existing
bounded scalar/encoded-text/DATETIME/text-clock signatures remain; nullable absence/NULL
keep effective-NULL semantics, not clause spelling. Required absence excludes an actual
default. Already-unsupported declaration/default-NULL preparation refusals move earlier,
including intermediate unsupported claims followed by relinquishment.

Actual archived9cf8fd9 SQLite writer/reader/runtime completed DEFAULT7 definition with
DEFAULT8 construction and stored8 on omission. Fixed real format2 artifact now refuses
load/typed preparation; isolated copied-source gate bypass reproduces current false
completion without worktree mutation during native suites. Native known mismatches now
refuse pre-DDL/no history rather than after effects; not native false completion.
Runtime catalog/recovery/drift guards unchanged. Valid old literal dump/digest/model-free
id42/default7 and generated Unicode/NUL/NULL/cosmetic-clock positives retained. No format/
ledger/receipt conversion or retrospective revocation/repair/authentication.

Not full SQL/attribute/key equivalence, default-value domain/constraint-fit certification,
Python constructor defaults, storage-hint/query/codec or clock/timezone/future-session/
application-readiness proof. Trusted executable SQL remains unsandboxed. Remaining
metadata/key/index/constraint/namespace/negative ownership/FK, workflow/interruption and
resource/compiler/package/codec/ledger queue open; points1–4 incomplete, draft/guides deferred.


### Historical query-source admission checkpoint

ColumnState.storage proposes a default historical constructor; it does not certify a
codec. Source generation now checks that candidate against the recorded definition:
SQLite INTEGER/TEXT/REAL/BLOB, native default BIGINT/VARCHAR(255)/DOUBLE/BLOB with known
physical aliases. INT/ANY, conflicting hints, wider/parameterized native text or native
Boolean/datetime/decimal/JSON/other policies need explicit adapters here, without losing
physical package support. This is not inference of arbitrary codecs from native families.

Actual archived6e6b0b1 source generation converted VARCHAR512/str/TEXT to defaultText255:
original-model update300 compiled, generated historical update300 rejected. Fixed real
format2 package retains exact load bytes/digest, native deployment completes and an
explicit query adapter writes/reads300. Automatic historical generation now refuses.
Copied-source primitive-gate bypass reproduces current lossy source; worktree unmutated
during native suites. Query-generation defect, not migration false completion/recovery.
Runtime target/catalog/drift/recovery guards unchanged; no format/ledger conversion.

Fresh logical metadata extraction accepts genuine builtin scalar unions only; other
generic origins/Annotated/native JSON payloads stay opaque instead of degrading their
type arguments into scalars/unions. Unhashable opaque nullable metadata no longer
blocks physical generation with a TypeError (also reproduced with the real old writer).
Recorded source annotation emission uses finite
builtin scalar names/unions, safely normalized, never evaluated. Known framework/type
name shadows, dunders and non-ASCII fields require name adapters. Default-primitive
scalar/nullable/union positives on both backends independently typecheck/import/compile
updates without authoring models. This is partial admission, not full namespace proof.

Old physical artifacts/receipts are not rewritten. Fresh opaque metadata changes to None
are truthful new generation, not conversion or recovered provenance. Old erased logical
origin/custom hooks cannot be inferred or retrospectively certified from scalar strings.
No durable codec ABI/provenance, value/JSON-shape/hook preservation, universal native
codec mapping or readiness certificate. General generation/metadata/resource/compiler/
package/codec/ledger evolution and key/constraint/FK/ownership/workflow/interruption
queue remains open; points1–4 incomplete, draft/guides deferred.


### Inline-primary-key declaration checkpoint

Compile/load binds managed inline key declarations/absence to construction, before/
target/intermediate CREATE/ADOPT despite relinquishment. Standalone ADD/ChangeDefault
key terms admitted independently. Extra SQL declarations do not manufacture claims.
SQLite signatures preserve direction, key ON CONFLICT policy and AUTOINCREMENT;
only known omitted ASC/ABORT defaults normalize. Following NOT NULL/UNIQUE policies
are not attributed to the key. Matching ASC/ABORT, DESC (distinct hidden rowid), IGNORE
(original duplicate retained) and AUTOINCREMENT (no greatest-id reuse) execute.
Native ordinary inline presence binds; explicit directions/unknown suffixes adapter.
Native identity/nullability/index/catalog guards remain independent and unchanged.

Actual archived6806ca6 SQLite writer/reader/runtime completed INTEGER PRIMARY KEY
metadata/no constructed key, accepting duplicate42 and NULL ids. Fixed real format2
artifact now refuses load/typed preparation; copied-source table-gate bypass reproduces
current false completion without working-source mutation during native suites. Valid
companion literal dump/digest/model-free id42/default7 retained. Native known missing/
hidden/moved inline-key examples move late refusal to pre-DDL/no history, not native
false completion. Accepted-catalog proof still refuses independently changed physical
keys for valid follow-ups. No format/ledger/receipt conversion or retrospective repair.

Literal/quoted/nested mentions are not declarations. Multiple/unsupported forms need
adapters; inline/table relocation is not automatically equivalent. Not full table-key
member/order/expression/prefix proof, effective key nullability, constraint naming,
NOT NULL/UNIQUE conflict policy, all rowid modes, namespace/index/FK, codec or readiness
certification. Trusted executable SQL remains unsandboxed; remaining claim/workflow/
interruption/resource/compiler/package/codec/ledger queue open, points1–4 incomplete,
draft/guides deferred.


### Declaration/key-implied nullability checkpoint

Recorded nullable flags bind independently to definition/construction key rules, including
before/target/intermediate CREATE/ADOPT despite relinquishment. SQLite plain TEXT/INT and
inline INTEGER PRIMARY KEY DESC remain nullable absent NOT NULL; exactly INTEGER with a
single non-DESC inline key aliases rowid. Table-level single INTEGER aliases even with
DESC; composite INTEGER does not. NULL input allocating a non-NULL rowid is not stored NULL.
Known STRICT/WITHOUT ROWID combinations require all key members; native supported keys
are required without an explicit NOT NULL clause. Full-column table membership is bounded:
known identifiers/directions/SQLite conflict clause only; unsupported expressions/prefixes,
duplicate/unknown/multiple keys and unknown modes need adapters. No new column authority
from extra SQL members; no key-change operation or naming/index equivalence implied.

Actual archived9eb468e SQLite writer/reader/runtime completed required TEXT-key metadata in
a non-STRICT table then stored two NULL ids. Fixed real format2 artifact now refuses load/
typed preparation; isolated copied-source gate bypass reproduces current false completion.
Truthful nullable old companion retains literal dump/digest/NULL-bearing deployment. Actual
archived native nullable table key left DDL/uncertainty/ambiguous recovery after late refusal,
not false completion; now pre-DDL/no-history refusal. Truthful native required counterparts
deploy. Native catalog/recovery guards unchanged. No format/ledger/receipt conversion,
retrospective repair/revocation or history recertification. Resource bounds remain partial.

Declaration/key-implied nullability is not general CHECK/FK/trigger/default/session/domain,
codec or readiness proof. Full key/constraint identity, UNIQUE/conflict/namespace/index/FK
compatibility and workflow/interruption/resource/compiler/package/codec/ledger queue remain
open; trusted SQL unsandboxed, points1–4 incomplete, draft/guides deferred.


### Inline UNIQUE construction checkpoint

Compile/load binds managed inline UNIQUE presence/absence to construction, before/target/
intermediate CREATE/ADOPT after relinquishment; standalone ADD/ChangeDefault terms admitted
independently. SQLite owns-clause ON CONFLICT and explicit label preserved (omitted ABORT
normalizes, label quoting only; no spelling/case fold). Following NOT NULL policy/label is
not UNIQUE's. Equal unknown/multiple clauses need adapters. Native plain UNIQUE/UNIQUE KEY
normalize; named native inline forms require adapters, not a cross-version/name claim.
Extra SQL columns/indexes do not manufacture authority; table-level/separate-index apparent
equivalence is not an automatic substitute, and named UNIQUE does not authorize DROP INDEX.

Actual archivedfd5f36e writer/reader/runtime falsely completed missing-UNIQUE construction
on **both SQLite and native**, then stored default7 duplicates under ids42/43. Real format2
invalid artifacts now refuse load/typed preparation; copied-source table-gate bypasses
reproduce current false completion. Valid old companions retain literal dumps/digests and
model-free default7/duplicate-refusal deployment. No format/ledger/receipt conversion,
retrospective repair/revocation or history recertification. Native guards unchanged, not a
new complete live UNIQUE catalog proof. Public transaction policy positives do not certify
all multi-statement error semantics. Nullable UNIQUE still permits multiple NULLs.

Whole key/table/index/constraint equivalence/namespaces, other constraints/policies, native
implicit index names, collation/NULL/index-family/version/FK compatibility, session/data
checks (unique_checks), logical codecs/readiness and workflow/interruption/resource/compiler/
package/codec/ledger queue remain open. Trusted SQL unsandboxed; points1–4 incomplete,
draft/guides deferred.


### Explicit NOT NULL clause checkpoint

Compile/load binds managed explicit NOT NULL presence, SQLite own ON CONFLICT and label
independently of effective key-nullability flags. Before/target/intermediate CREATE/ADOPT
remain claims after handoff; standalone ADD/default terms admitted independently. Known
ABORT omission/label quoting normalize, not label presence/spelling/case. Following UNIQUE/
PK policies are not NOT NULL's. Extra SQL columns do not manufacture ownership; a NOT NULL
label is not DROP CHECK authority. Native plain requiredness supported; named native and
SQLite-style policies require adapters, not cross-version syntax/coercion guesses.

Actual archived86464d6 writer/reader/runtime completed IGNORE metadata/REPLACE construction,
then inserted id42/default7 on a NULL write instead of skipping. Real format2 artifact now
refuses load/typed preparation; copied-source gate bypass reproduces current false
completion. Truthful old IGNORE companion retains literal dump/digest/NULL-write skipping.
Live policies distinguish skip/substitution/rejection, including absent/NULL-default REPLACE
fallback. Not a full multi-statement error ABI. Native strict-consumer positive is not future
session policy proof. No native false-completion claim, format/ledger/receipt conversion,
retrospective repair/revocation/history certification or new native recovery guarantee.

Declaration/key/catalog guards remain separate. Whole NULL/CHECK/FK/other constraint identity/
namespace, collation/generated/other attributes, index/FK/data/session/codec/readiness and
workflow/interruption/resource/compiler/package/codec/ledger queue remain open; trusted SQL
unsandboxed, points1–4 incomplete, still draft/guides deferred.


### Explicit inline primary-key label checkpoint

Bind managed optional SQLite PK labels separately from direction/conflict/AUTOINCREMENT/
effective nullability. Known quotes normalize, not presence/spelling/case; following NOT
NULL/UNIQUE names are separate. Unsupported string-role names and named native inline
forms need adapters, not syntax/retained-name/PRIMARY-index inference. Before/target/
intermediate claims survive handoff; standalone terms admitted without final ownership.
Extra SQL named keys do not create recorded columns/indexes or DROP CHECK/INDEX authority.

Archivede1d3ef0 emitted/loaded/completed a real format2 package recording label "recorded"
but constructing/cataloging "other". Identity contradiction, not lost uniqueness/changed
write behavior; no native runtime false-completion claim. Current literal load/typed prepare
refuse before effects/history; truthful companion retains dump/digest/default7/duplicate
refusal. Isolated copied-source label-only comparison omission reproduces it. Named SQLite
ordinary/DESC/AUTOINCREMENT positives retain key behavior. No conversion/repair/retrospective
certification; whole key/index/constraint namespace, other attributes/policies and queue
remain open. Trusted SQL unsandboxed; points1–4 incomplete, draft/guides deferred.


### Column collation construction checkpoint

Bind managed SQLite BINARY/NOCASE/RTRIM, implicit BINARY and optional COLLATE labels;
known quotes/name keyword case normalize, not label presence/spelling/case. Custom/duplicate/
unknown suffix/string-role forms require adapters. Native existing type-prefix utf8mb4/
JSON-bin name contract reused; omission is not assumed equivalent to an explicit name.
Not charset inheritance, locale/Unicode/version/custom registry/override/equivalence proof.
Before/target/intermediate claims survive handoff; standalone terms need admission without
final ownership/operation permission; extra SQL fields don't create ownership/authority.

Archived8e7c243 real format2 NOCASE/BINARY falsely completed then accepted default 'Case'
and 'case' under UNIQUE; literal load/typed prepare now refuse before effects/history.
Truthful old NOCASE companion retains dump/digest/default/case-only duplicate rejection;
isolated copied-source table-gate bypass reproduces. Archived native bin/general_ci committed
DDL then refused UNCERTAIN/AMBIGUOUS, not native false completion; now pre-DDL refusal.
Live built-in SQLite/native named comparison positives and independent post-completion
catalog drift guard retained. No conversion/repair/retrospective certification, no full
collation/index/FK/data/session/codec/readiness proof. Other attributes/constraints/charset/
generated/namespaces/FK/workflow/interruption/resource/evolution queue open; trusted SQL
unsandboxed, points1–4 incomplete, draft/guides deferred.


### Native AUTO_INCREMENT construction checkpoint

Bind managed native generator presence/absence independently of key/storage/nullability.
Before/target/intermediate CREATE claims survive handoff; standalone language admission
independent of final ownership/operation permission, not native adoption/alter-key support.
Extra SQL generators/indexes don't create recorded ownership/destructive authority. Existing
bounded attribute prefix/case reused; duplicates/equal unknown positions require adapters;
identifier/default/comment/literal mentions aren't attributes. SQLite identity unchanged.

Archived9b4b442 real format2 emitted/loaded/prepared generator metadata/plain construction,
committed DDL then refused UNCERTAIN/AMBIGUOUS: not false completion. Literal load/typed
prepare now refuse pre-effects/history; truthful companion retains dump/digest/generation/
default7/counter-tolerant followup. Isolated copied-source gate bypass preserves late refusal/
uncertainty, working sources untouched during native suites. Independent post-completion
physical generator drift guard kept. No conversion/repair/retrospective certification,
exact counter/sequence/no-gap/non-reuse/range/zero-mode/offset/increment/future-session/codec/
readiness proof or recovery shortcut. Other attributes/generated/visibility/constraints/
namespaces/FK/workflows/interruption/resource/evolution queue open; trusted SQL unsandboxed,
points1–4 incomplete, draft/guides deferred.


### Native column visibility construction checkpoint

Bind managed implicit ordinary visibility/INVISIBLE independently of named queryability and
other column facts. Before/target/intermediate CREATE claims survive handoff; standalone
language admission independent of final ownership/operation permission, no native adoption/
visibility alteration added. Extra invisible SQL columns don't create ownership/authority.
Existing bounded recognizer reused: known keyword case; explicit VISIBLE/repeated/conflicting/
unparsed roles still adapter-only, now compile-refused. SQLite unchanged, generated expression
identity/equivalence not certified. Visibility is not access control/query projection ABI.

Archived566229c real format2 emitted/loaded/prepared ordinary metadata/INVISIBLE construction,
committed DDL then refused UNCERTAIN/AMBIGUOUS: not false completion; current literal load/
typed prepare refuse pre-effects/history. Truthful companion retains dump/digest/wildcard
omission/positional default7/named access; isolated copied-source gate bypass retains late
catalog refusal/uncertainty, working sources untouched during native suites. Independent
post-completion physical visibility drift guard retained. No conversion/repair/retrospective
certification/recovery shortcut/full data/session/codec/readiness proof. Other generated/
ON UPDATE/attributes/constraints/namespaces/FK/workflow/interruption/resource/evolution queue
open; trusted SQL unsandboxed, points1–4 incomplete, draft/guides deferred.


### Generated kind/finite scalar expression checkpoint

Bind managed generated presence/kind/expression and SQLite label independently of other
column facts. Known VIRTUAL/default/GENERATED ALWAYS/native STORED/PERSISTENT normalize;
label presence/spelling/case bind, quotes cosmetic. Finite signed64 decimal/string/NULL,
quoted declared member, quoted member plus integer, native integer CAST AS SIGNED. Native
backticks required, unquoted references/unknown functions/rewrites/roles/missing members need
adapters even equal bytes.64 expression tokens pre-normalization/19-digit integers; not
total-work/memory bound. Before/target/intermediate CREATE/SQLite ADOPT claims survive handoff;
standalone admission without member scope, not new generated ADD/alter permission. Extra SQL
generated expressions trusted/unclaimed, labels not DROP CHECK authority.

Archived6af49f5 actual format2 writers/readers/runtimes falsely completed AS7/AS8 VIRTUAL on
BOTH SQLite and MariaDB, returned value8 under base7 insert. Literal load/typed prepare now
refuse pre-effects/history; truthful companions retain dump/digest/model-free base7/value7;
isolated copied-source gate bypasses reproduce both current false completions, working sources
untouched during native suites. Known derived-value mode positives and independent later
physical expression drift guards retained. No conversion/repair/retrospective certification,
arbitrary/live expression equivalence/dependency/cycle/type/DDL validity/generated query
writability/codec/all-session/data/readiness proof or recovery shortcut. ON UPDATE/other
attributes/constraints/namespaces/FK/workflow/interruption/resource/evolution queue open;
trusted SQL unsandboxed, points1–4 incomplete, draft/guides deferred.


### Native ON UPDATE construction checkpoint

Managed native ON UPDATE presence/precision binds corresponding executable column, before/
target/intermediate CREATE after handoff and standalone ADD/ChangeDefault admission. Existing
DATETIME/TIMESTAMP CURRENT_TIMESTAMP language/column-inherited omitted or empty precision/
explicit matching0–6/keyword case retained. Unknown function/position/suffix/multiplicity/
precision needs adapter even equal bytes. Extra SQL automatic fields unowned; no new temporal
alteration/ADD permission/native adoption/destructive authority. SQLite unchanged.

Bounded FK parser owns ON DELETE/UPDATE actions; native REFERENCES tail SET NULL is not
ordinary column nullability. Actions must parse, later clauses/unknown roles fail closed,
not blanket suppression. Known action compile positives/existing live default-action guard/
separate-table SET NULL behavior retained, not full FK compatibility/session certificate.

Archived692e316 actual format2 writer/reader/runtime committed missing-ON-UPDATE construction
then refused completion, UNCERTAIN/AMBIGUOUS (NOT false completion). Literal load/typed prepare
now pre-effects refusal, truthful companion retains dump/digest/model-free deployment; copied
current-source gate-only bypass preserves late refusal/committed effects/uncertainty. Worktree
unmutated during native suites. No conversion/repair/retrospective certification. Live session-
clock cases distinguish NULL default/changed-write automatic timestamp/explicit unchanged-field
suppression, accepted-catalog drift guard retained. Not exact/monotonic clock/timezone/all writes/
privilege/future-session/data/codec/readiness or recovery proof; no server policy mutation.
Remaining attributes/constraints/namespaces/FK/combined workflows/interruption/resources/compiler/
package/codec/ledger/release queue open; points1–4 incomplete, trusted executable SQL unsandboxed,
draft/guides deferred, not production/merge-ready.


### SQLite inline CHECK construction checkpoint

Bind managed column CHECK bodies bidirectionally, own labels/order/multiplicity. Significant
token kinds/order/punctuation/string values bind; known label/reference quotes and ASCII
keyword/member case normalize, label spelling/case/presence do not. Existing finite CHECK
grammar/resources (4096/32/64/4096) admit expressions/members, not AST/algebraic equivalence.
Unknown function/constant or bare-column body/nested COLLATE/suffix/inline ON CONFLICT/name
roles need adapters even equal bytes; no bare/quoted/operator/parenthesis/reorder inference.
Declared extra members can be referenced without ownership; extra SQL fields' own opaque and
table-level CHECKs unclaimed/trusted. Standalone own-member scope only, not new operation
permission. Before/target/intermediate CREATE/SQLite ADOPT claims survive handoff; inline
labels not named table DropCheck authority. Native CHECK path unchanged/separately partial.

Archived2efa8f4 actual format2 writer/reader/runtime falsely completed missing-CHECK SQL,
accepted default7 AND forbidden-1. Literal load/typed prepare now pre-effects refusal;
truthful companion retains body/digest/model-free default7/rejection. Copied current-source
gate-only bypass reproduces false completion with other guards enabled; source unmutated
during native suites. No conversion/repair/revocation/retrospective certification. Nullable
SQL-NULL acceptance/negative rejection, explicit adoption→handoff→re-adoption, preserving
default-change rebuild with opaque extra length CHECK and independent catalog drift guard
retained. Not arbitrary/live equivalence/DDL-validity solving/total parser or IO/memory bound/
current or future enforcement-session/data/privilege/codec/readiness or recovery certificate.
Remaining native/attributes/constraints/namespaces/FK/combined interruption/resources/compiler/
package/codec/ledger/release queue open; points1–4 incomplete, trusted SQL unsandboxed,
draft/guides deferred, not production/merge-ready.


### SQLite inline REFERENCES construction checkpoint

Bind managed inline REFERENCES presence/explicit unqualified target+one member/CASCADE,
RESTRICT, NO ACTION/own label. Known identifier quotes/ASCII names+keyword case/action
ordering/omitted NO ACTION normalize; NO ACTION DISTINCT from RESTRICT, label presence/
spelling/case bind. Unknown implicit parent key/composite or qualified targets/string roles/
member expressions/multiple references/duplicate actions/MATCH/timing/SET actions need
adapters even equal bytes. No full FK syntax/SQL validity/resource certificate. Before/
target/intermediate CREATE/SQLite ADOPT after handoff and standalone ADD/ChangeDefault
admission independent of final ownership/operation permission; extra SQL field references
unclaimed/trusted, no parent adoption/extra child ownership/DropCheck authority. Generated
table-level FKs/native path unchanged and separately partial.

Archived51e4b74 actual format2 writer/reader/runtime falsely completed missing-FK SQL,
accepted orphan999 with foreign_keys1. Literal load/typed prepare now pre-effects refusal;
truthful companion retains body/digest/model-free parent/NULL-child/valid-child/orphan
rejection. Copied current-source table-gate-only bypass reproduces false completion with
other guards active, source untouched during native suites. No conversion/repair/revocation/
retrospective certification. Live CASCADE update/delete and independent later physical-action
drift guard retained. Not parent existence/key/index/type/collation/namespace/privilege/full
compatibility/current or future enforcement-session/data/codec/readiness or recovery proof.
Query/model mapping/parent ownership separate; SET forms/other attribute-role integration,
namespace/constraint/FK/combined workflow/interruption/resource/compiler/package/codec/ledger/
release queue open; points1–4 incomplete, trusted SQL unsandboxed, draft/guides deferred,
not production/merge-ready.


### SQLite referenced-parent base-table checkpoint

Pending preparation projects the catalog through supported steps and requires ordinary
parent tables for claimed inline/table-level FKs; endpoint repeats proof before completion.
Before/target/intermediate CREATE/SQLite ADOPT references survive handoff, parent not adopted,
extra SQL child-field opaque references unclaimed. Ordinary catalog table+CREATE TABLE, not
view/CREATE VIRTUAL TABLE; relevant parent definitions only, ASCII identifier folding. Explicit
same-package parent creation either order works as final projection, not every-step DML
readiness. External ordinary parents remain unowned, constrained FK ADD remains unsupported.
Native path unchanged, not full syntax/virtual module/shadow/namespace/privilege/resource proof.

Archivedb106fd1 real format2 writer/reader/runtime completed matching FK DDL with missing
external parent and unusable child writes: readiness gap, NOT missing/mismatched-FK construction.
SAME artifact retains dump/digest/load/model-free external-parent/NULL-child/valid-child/orphan
rejection. Missing/view/virtual parent pending prepare now read-only pre-effects refusal.
Copied preparation-only bypass proves endpoint child+ledger rollback; validator-only omission
at both call sites reproduces old context; working sources untouched during native suites.
No conversion/repair/revocation/retrospective certification; old complete/already-applied
receipts remain earlier execution evidence, not new readiness certification. Parent replacement
after prepare and post-completion removal still blocked by catalog revalidation/drift guards.
Not parent-key/member/index/type/collation/uniqueness/data/current or future enforcement-session/
codec/query readiness/full FK compatibility or recovery proof. Remaining constraint/namespace/
FK/combined workflow/interruption/resource/compiler/package/codec/ledger/release queue open;
points1–4 incomplete, trusted SQL unsandboxed, draft/guides deferred, not production/merge-ready.


### SQLite explicit referenced-member checkpoint

Pending projected/live endpoint parent proof now includes declared physical column presence
for explicit inline and single/composite table-FK member lists. ASCII folding/decoded quotes,
not undeclared rowid aliases/labels/literals/Unicode folding/query aliases. Actual rowid-named
columns work; unknown table-FK member string/expression/option/malformed roles require adapters.
Before/target/intermediate CREATE/SQLite ADOPT claims survive handoff, extra SQL child-field
opaque inline references unclaimed, no parent adoption/constrained ADD permission. Implicit
table-FK lists retain base-table observation ONLY, implicit-key resolution separate; no inline
language expansion. Native unchanged. Independent stale-plan/accepted-catalog guards retained.

Actual archived7b20272 format2 writer/reader/runtime completed matching FK DDL with ordinary
parent but missing explicit member, then child writes failed under foreign_keys1: bounded
member-readiness gap, NOT missing/mismatched-FK construction or orphan acceptance. SAME frozen
body/digest/load works old/current with declared member, valid/NULL children and orphan
rejection. Pending prepare refuses pre-effects; copied member-gate-only omission reproduces,
preparation-only bypass retains old base-table proof and new endpoint member proof, rolls
back child+ledger, leaves external parent. Working sources untouched during native suites.
No artifact/digest/ledger/receipt conversion, repair/revocation/retrospective certification;
old complete/already-applied receipts not new readiness certificates. Not arity/key/unique/
index/affinity/type/collation/implicit-key/data/current or future session/codec/query-readiness/
full FK/IO/deadline/total-memory/resource or recovery proof. Remaining queue open; points1–4
incomplete, trusted SQL unsandboxed, guides deferred, draft/not production/merge-ready.


### Workflow-first authoring checkpoint

See the [workflow review](recorded-migrations-workflow-review.md): actual generated models and
historical source, one logical expand/typed-backfill/require/drop revision, author-owned route
edit makes the old artifact stale, real static rejection of a wrong role type, authoring source
deleted before model-free deployment, current typed application verify/read/insert on SQLite
and private MariaDB. No state/declaration patches, raw migration SQL or production changes.
Both normal/forced-lazy child execution modes exercised. Initial incomplete author program
was refused for NULL rows, not a library defect; status/type-diagnostic expectation corrections
excluded. Largest measured friction: manual draft stitching via undeployed intermediate package.
Next priority is a small staged-authoring interface, not additional verifier breadth. Genuine
evolution, ownership/preservation, interruption/coordination, resources and finite release scope
remain open. Guides deferred, trusted SQL, no retrospective certification, draft/not merge-ready.


### Model-derived staged authoring

Draft.advance(models, removals=..., defaulted_additions=...) appends a complete stage inside
real revision/predecessor, retaining before-state/prefix/checkpoints/typed work. Shared state-
based generation, no exposed/serialized intermediate package, fake revision or caller state
stitching. Existing unresolved prefix refuses with resolve-current-stage guidance; new removal
choices resolved ONLY inside new stage before composition, so index/CHECK drops cannot precede
earlier creation/checkpoints. Incomplete/unknown/unsupported choice refuses, original draft
unchanged. Compiler validates prefix/composition, stale/late typed work still refuses. Explicit
handoff remains non-destructive, same-route recreation refused; defaults/adoption/destruction/
constrained ADD language unchanged. Both-backend SAME journey produces literal committed61036d9
packages; no wire/format/identity/ledger change. No total-work/memory promise. Historical-source/
model-repetition/freshness ergonomics and other workflow/evolution/recovery/release scope open;
not another verifier slice, guides deferred, SQL trusted, draft/incomplete/not merge-ready.


### Combined ownership lifecycle checkpoint

[Ownership review](recorded-migrations-ownership-review.md): SAME actual SQLite role journey
with typed query-only external mappings, zero-SQL strict adoption, external additions after
adoption, explicit preservation review/rebuild and zero-SQL handoff. Notes/default/generated
values/index/view/trigger/audit/child FK and live enforcement retained, mappings never imply
ownership. Clean strict re-adoption completes; preserved additions refuse re-adoption with
either preservation flag, history stops003 without repair/deletion/stamping. External old-flag
view dependency refuses002 at preparation, original schema/rows/view usable. No production,
parser/adoption/native/operation authority changes. Existing strict versus partial adoption
limit is now concrete; finite scope/design decision, not a new execution defect. Genuine
evolution/recovery/coordination/resources/release scope open; guides deferred, trusted SQL,
no retrospective or blanket readiness certificate, draft/incomplete/not merge-ready.


### Genuine application-codec evolution checkpoint

[Evolution review](recorded-migrations-evolution-review.md): actual replaced Pydantic serializer/
validator at same import path, same logical type/model/storage. Both-backend archived704fd44
packages preserve literal body/digest/load/scalar bindings/old receipts with no model/codec
imports at deploy. New-codec re-author changes bindings and Package.check refuses stale; schema
checkpoint digest unchanged and generation no schema ops because opaque query_type is None,
NOT codec ABI/provenance. Automatic historical source refuses; explicit v1 author model/wire
adapter required. Current app structural verification passes but logical decode refuses until
new003 explicit old-wire→new-wire data rewrite. No historical conversion/replay/receipt rewrite.
Author-program RED matched no old rows with new predicates; corrected on fresh fixture, not
library semantic-proof claim. Genuine FRAMEWORK compiler/package-format/ledger evolution,
codec provenance policy, recovery/coordination/resource/release/partial-adoption scope remain.
No production or parser changes, trusted SQL, readiness separate, guides deferred/draft.


### Actual framework capability/package/ledger evolution checkpoint

[Framework review](recorded-migrations-framework-evolution-review.md): archived2ab4e55 and033ba56
actual format2 writers/SQLite+private MariaDB runtimes, actual old001 complete receipts. Current
retains eleven-column receipt unchanged, deploys committed old002/003, compiles new model-derived
format5 index004, current typed app verifies/reads/inserts. Old compiler refuses index transition;
old reader refuses actual new bytes. Nine-column old ledger: current status/prepare refuse with
all receipt/schema/values unchanged, no conversion/replay/history deletion/retrospective upgrade.
In-suite SQLite regressions restore actual old SQL dumps; separate native archived-process traces.
Target-specific plan hashes compare against OWN original, not cross-target equality. No handbuilt
states/receipts; real generated historical module statically imported for typed backfill. No new
production code. Existing-operation emission remains compatible only for selected chain; load
still recompiles, canonical compiler/epoch/refusal policy open. No broad compatibility, downgrade,
uncertainty/resource/readiness guarantee. Recovery/coordination and finite scope next, guides deferred.


### Real role-process interruption and operator workflow checkpoint

[Recovery workflow review](recorded-migrations-recovery-workflow-review.md): three REAL releases,
model generation/actual historical source/static typed backfill/advance; deploy committed bytes
without author sources. SQLite DELETE reader/journal + external-process busy observation, actual
migrator SIGKILL, rows/expanded schema rollback with no003 receipt; two prepared retries converge
applied/already_applied. Not WAL active-death proof. Private native row2 lock observes firstUPDATE
modified>=1; unrelated unowned audit typed write commits during migration lock. Kill child,
disconnect rollback leaves durable uncertain003 ack0, kill/restart OWNED server, write/uncertainty
survive. Blind apply refuses; ORIGINAL Prepared JSON inspect/resume, two assessed resumers yield
applied/refused-completed-status requiring reassessment, terminal fresh apply already_applied.
Current app verifies/typed reads/inserts on both. No injected/private helper faults, no ledger
edits/automatic repair/replay/retrospective certificate. Operator-program REDs are safe refusals,
not product runtime defects; fixture/cache/type/timeout issues excluded. Original plan immutable,
no stable Prepared wire ABI promised. Finite supported scope, WAL/other receipt-loss windows,
compiler/codec/partial adoption remain open. Advisory coordination != application pause/fencing
or same-table writer safety; schema exclusion caller-owned. No production changes, guides deferred.

## SQLite writer acquisition disposition

The [SQLite coordination checkpoint](recorded-migrations-sqlite-coordination-review.md)
classifies exact BEGIN IMMEDIATE/SQLITE_BUSY as known acquisition refusal, keeping the
synchronized target usable. Real original role plans cover grant/refusal and interrupted
I/O/task/scope waits; unsafe workers are independently disposed before fresh status/apply.
The busy-handler acquisition budget and per-I/O deadline remain separate, not a new end-to-end
client clock. Session/journal/durability, remaining outcome/shutdown policy and G4/G5 stay open.

## Native UTC admission follow-through

The [native UTC checkpoint](recorded-migrations-native-utc-review.md) applies/readbacks the
shared ordinary runtime UTC policy before yielding a dedicated native target, through owned
per-I/O deadlines. Actual frozen role/clock work under non-UTC server defaults now agrees with
ordinary DATETIME/TEXT UtcDatetime reads/writes; SQL-mode rendering evidence is not normalized
away and old rows/receipts are never repaired. This is only UTC session admission, not version/
metadata/strictness/enforcement admission or complete G3. Journal/durability and remaining
outcome/shutdown policy, G4/G5 and release decisions remain open.

## SQLite encoding/FK admission follow-through

The [SQLite admission checkpoint](recorded-migrations-sqlite-admission-review.md) applies and
verifies shared foreign_keys/UTF-8 policy before yielding a dedicated target, through owned
per-I/O deadlines. Real UTF-16 files refuse without byte/schema/data/history conversion; an
explicitly different UTF-8 target deploys original role packages and normal typed application.
The ordinary fixed busy wait/WAL/synchronous initializer is deliberately NOT imported, so
migration acquisition and pending journal/durability policy are not silently changed. This is
not complete SQLite runtime admission, failure-window qualification or completion of G3/G4/G5.

## Native integrity admission follow-through

The [native integrity checkpoint](recorded-migrations-native-enforcement-review.md) verifies
shared foreign_key_checks/check_constraint_checks/unique_checks1/ON prerequisites before
native Target yield. It does NOT implicitly enable disabled settings or repair GLOBAL state;
UTC remains the sole native normalization, preserving actual SQL-mode/rendering/recovery
facts. Real disabled-default refusals preserve original role plans/earlier receipts/data;
explicit caller restoration permits original work. Version/strictness/metadata, journal/
durability, remaining outcome/shutdown policy and G4/G5 remain open, not implicitly qualified.

## SQLite journal/synchronization follow-through

The [SQLite synchronization checkpoint](recorded-migrations-sqlite-durability-review.md)
admits/preserves DELETE/WAL and applies/readbacks shared Config NORMAL1/FULL2 per connection,
without importing ordinary fixed busy waits or silently forcing WAL. Real original-role
backfill triggers independently observe that session's actual sync/journal/busy values;
original evidence/earlier receipts remain. Prepared/receipts do not certify disk policy or
power loss; NORMAL now explicitly requests1 rather than coincidentally inheriting2. Ordinary
runtime still selects WAL. Memory remains native/volatile. Remaining G3 outcome/admission/
shutdown/native prerequisites and G4 WAL-death/matrix/native lost-ack/G5 approval remain open.
