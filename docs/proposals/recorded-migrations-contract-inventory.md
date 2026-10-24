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
  additions now have a bounded format-5 route; index removal/replacement and CHECK
  alterations remain unsupported.
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
windows. Index removal/replacement, CHECK changes and the broader audit queue remain open.

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

Next: explicit index removal/replacement with negative postconditions, then bounded
CHECK changes. Construction/claim authority, unexpected-object ownership boundaries,
FK referenced-column/index/type proof, broader workflow/recovery/resource/evolution
coverage remain unfinished. Guides/release-scope/API reconciliation are deferred.
