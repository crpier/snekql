# Recorded migrations: bounded promotion scope (#477)

Status: **G5 engineering contract accepted for bounded opt-in first promotion**, not publication.
Original proposal baseline: `fa45f57`, draft PR #482. Current G5 acceptance and explicit ADR
amendments are recorded below; this is not publication or a general support promise. Consumer
and release documentation must follow before publication.

This consolidates completed workflow evidence into the bounded first-promotion contract. Earlier
reviews are evidence for their own checkpoints, not an ever-growing release checklist.
[ADR 0023](../adr/0023-recorded-migration-ownership-and-execution.md) records the architectural
trade-off; the [glossary](../../GLOSSARY.md) distinguishes ownership, mapping and readiness.

Current lifecycle policy is summarized under **G3** below and the
[retained-cleanup review](recorded-migrations-retained-cleanup-review.md). The chronological
follow-through entries record their checkpoint's limits, not today's remaining checklist.
Candidate G3 decisions are recorded; local WAL active-backfill process death is now exercised.
The finite G4 matrix and selected WAL/COMMIT/DDL windows are now exercised; completed broad
validation for that checkpoint is recorded in the G4 review. The G5 change is separately
requalified below; architectural acceptance does not authorize merge or publication.

Consumer/release documentation and isolated candidate packaging are now complete
for review; see the [consumer packaging follow-through](recorded-migrations-consumer-release-review.md).
That later checkpoint does not select a version, authorize publication, widen finite
runtime support, or change the experimental namespace. Earlier chronology below
remains evidence for its own source/checkpoint.

## G5 explicit lifetime review

The maintainer selected B: a public connection lifetime retained BEFORE opening, with bounded
`wait_closed()` after failed entry/exit. The [G5 decision review](recorded-migrations-g5-decision-review.md)
records names, in-process lifetime adequacy, raw/recorded coexistence and the intended ADR
amendments. New frozen source now passes216 matrix cases/12rows,956+956experimental/1784fast/
160+160focused/negative1+1. G5 is accepted for that bounded opt-in experimental contract.
Prior G4 completion is historical evidence, not validation of the interface change; full new
qualification is recorded in the G5 review. Consumer/release documentation follows before
publication. No stable replacement/namespace move, merge/tag/version/publication is authorized.

## Versioned original-evidence follow-through

The [prepared-evidence checkpoint](recorded-migrations-prepared-evidence-review.md) implements
`Prepared.dump/load`: a bounded version1 integrity envelope, required execution_epoch1 in new
ledger-bound plans, and explicit incompatible/raw-unversioned refusal. Real deferred SQLite
preservation/replacement-worker application and native client-death/server-restart resume use
retained original evidence. Historical package bytes and completed receipts are not converted.
That G2 persistence foundation did not itself complete G1: at that point standalone Package.load
still used public current compilation and ordinary apply used unversioned target lowering.
The subsequent defined interpretation is described below. Durable storage and the
ledger's observation evidence remain caller responsibilities; no host-loss or generic upgrade
promise. Candidate support and the remaining gates below are still proposed/incomplete.

## Defined historical execution follow-through

The [execution-epoch checkpoint](recorded-migrations-execution-epoch-review.md) now binds legacy
formats2–8 to a defined epoch-one canonical interpreter and target lowerer, independent of the
public current authoring verb. Package bytes stay unchanged; capability admission and epoch
mapping are separate. Actual isolated changed contraction grouping makes current authoring
stale/refused as epoch one while original package/Prepared execution still works. Only epoch
one is supported, not a general registry or automatic future conversion. Live admission and
endpoint checks remain; runtime policy, finite qualification and release decisions stay open.

## Checked-out I/O deadline follow-through

The [bounded G3 checkpoint](recorded-migrations-io-deadline-review.md) now guards checked-out
cursor/statement/fetch/cleanup and transaction-control waits with fresh operation deadlines.
Timeout/cancellation invalidates the target; SQLite physical close can finish later. An actual
DELETE-mode COMMIT completed AFTER its timeout and was resolved from fresh evidence, not a
rollback assumption. Native partial-backfill expiry retained original-plan uncertainty/recovery.
Opening/acquisition policy, session/config/durability integration and other G3 outcome/shutdown
questions remain; this is not completion of G3 or finite environment qualification.

## Native opening follow-through

The [native-opening checkpoint](recorded-migrations-native-opening-review.md) adds a bounded
acquisition scope around native connection establishment/authentication, with partial ownership
and the existing mandatory-TLS policy shared with ordinary runtime pool filling. Actual TCP
peer EOF/zero bytes, both caller-cancellation styles, plaintext refusal despite configured TLS,
and unchanged frozen-role deployment/current typed use over verified TLS are exercised. SQLite
opening, local guard/server coordination acquisition, session/durability and remaining outcome/
shutdown rules are still open. No universal physical-stop or completed G3 claim follows.

## SQLite physical opening follow-through

The [SQLite-opening checkpoint](recorded-migrations-sqlite-opening-review.md) bounds physical
opening separately from SQLite busy waits and checked-out I/O. Timeout/cancellation retains an
owned opening future and explicitly closes its eventual handle; it does not admit late package
work. Actual Linux leases demonstrate continuing kernel waits after caller completion, then
worker/FD disposal before fresh frozen-role deployment. A naive timer-only negative control
produced an unclosed-database ResourceWarning. Local guard/server coordination acquisition,
session/journal/durability, remaining outcomes and shutdown policy are still open; a retained
in-process task is not a physical-stop, loop-shutdown or host-loss guarantee.

## Local target-guard follow-through

The [local-guard checkpoint](recorded-migrations-local-guard-review.md) bounds each caller's
local guard wait, not the admitted operation's lifetime. Expired/cancelled queued callers do
not touch/discard the current owner's connection. Real partially modified native role work
remains on the same server connection after queued status/prepare/apply expiry or caller
cancellation, then completes on that same target with original bytes/current typed use.
Server coordination acquisition, session/durability and remaining outcome/shutdown policy are
still open; this does not fence other writers, supply new fairness or complete G3.

## Native server coordination follow-through

The [native coordination checkpoint](recorded-migrations-native-coordination-review.md)
preserves fractional GET_LOCK server waits and reports known non-acquisition with the existing
MigrationLockTimeoutError while retaining the synchronized contender. Real role grant/refusal
and I/O/task/scope interruption preserve the separate active owner, original evidence and typed
application. Unsafe contenders are discarded and server disconnect is independently observed.
Server wait and driver operation deadlines are distinct; this is not a new end-to-end client
acquisition clock. SQLite writer coordination and remaining G3 policy are still incomplete.

## Recommendation

Retain the opt-in experimental interface until the five gates below are satisfied. The first
promotion should support reviewed, linear schema-and-data changes during a caller-arranged
maintenance window, not promise online schema change or general crash-proof execution.
Do not replace released `Database.migrate`/`verify_migrations`, convert their histories, or
change initialization as a side effect of this work. Choose any eventual replacement and
release version explicitly; neither is decided here.

- Query mapping does not acquire migration ownership. Selecting desired models for generation
  is explicit authoring input, not permission inferred from ordinary application use.
- Recorded ownership can cover selected tables while other mapped tables remain unowned.
  Retaining extra facts during a supported rebuild does not adopt them.
- Arrange exclusion of competing schema writers and incompatible writers of affected data
  before preparation, and maintain it through application/recovery and readiness checks.
  Migration locks coordinate participating operators; they do not provide this exclusion.
  Unrelated compatible application work need not be globally paused.
- Completion proves only the declared, supported migration obligations. Current structural
  verification, codec/data checks and rollout readiness remain separate caller decisions.
- Unsupported or uncertain work stops. There is no force-complete, automatic repair, history
  stamping, inferred data replay, or retrospective upgrading of an old receipt's meaning.

## Candidate environment matrix

These are the **finite candidate qualification set**, not an accepted G5 release contract.
Completed normal/lazy evidence is recorded in the [G4 review](recorded-migrations-g4-qualification-review.md). Use the
released [MariaDB policy](../mariadb-support.md) as a source of target families, not as evidence
that the experimental connection has inherited its admission/session/runtime guarantees.

| Dimension | Proposed first promotion | Evidence and remaining qualification |
| --- | --- | --- |
| Python/platform | GIL-enabled CPython 3.15 on Linux, default asyncio | Actual3.15.0 GIL builds on local Linux x86_64/default asyncio qualified; exact versions/maps recorded. No Windows/macOS, alternative event-loop or free-threaded promise. |
| SQLite | Actual 3.45.1 and 3.53.1 builds; file-backed DELETE and WAL | Both actual builds run selected normal/lazy authoring/codec/ownership/refusal and DELETE-WAL/NORMAL-FULL journeys, including actual WAL active-client death. No inference from existing Actions jobs. |
| MariaDB | Maintained Community LTS 10.11, 11.4, 11.8 and 12.3; InnoDB | Actual10.11.19/11.4.13/11.8.9/12.3.3 builds run selected normal/lazy workflow/refusal/codec/handoff/COMMIT-DDL loss. Actual /proc executable hashes/VERSION recorded;13.0.2 remains regression-only. |
| Regression-only native targets | 12.2 catalog regressions and rolling/newer binaries | Passing these does not promote a series to a maintained target. The known malformed escaped-FK catalog form remains refused. MySQL is excluded. |

Record exact Python/driver/server/SQLite versions, OS and completed reports. An admitted
version number, pending CI, or a released backend test is not an experimental qualification.
No claim covers every intervening version or patch, in-place engine upgrades, data-directory
downgrades, replication, host/volume loss or power-loss/storage-stack behavior. SQLite FULL
versus NORMAL durability must not be inferred from the journal-mode experiment or from merely
passing an application Config to the experimental connector.

## Finite product surface

This is a transition repertoire, **not** acceptance of arbitrary SQL or every model declaration.
Construction/claim agreement, observation, negative postconditions and existing fail-closed
checks stay in force. The [prototype](recorded-migrations-prototype.md) and
[contract inventory](recorded-migrations-contract-inventory.md) describe the bounded grammars.

| Candidate capability | Explicit limit |
| --- | --- |
| Model-derived CREATE and subsequent nullable ADD | Supported declarations only; ADD is unconstrained and nullable. Required additions need an explicit nullable stage/backfill. Defaulted additions require the explicit `leave_null` policy, not an inferred fill. |
| Typed data work at named intermediate contracts | Frozen parameterized UPDATE and scalar bindings; no runtime Python, arbitrary extension callbacks, INSERT/DELETE migration interface or resumable long job. Author/build checks supplied current routes; deployment cannot discover unprovided source edits. |
| Staged changes | `then`/`advance` retain one real revision and lineage; unresolved choices refuse. Explicit removals authorize drop-column, recorded secondary-index and named table-CHECK operations only. No implicit DROP TABLE or rename inference. |
| Existing-column changes | Ordinary require/allow-NULL and bounded default changes; no general storage/type/collation conversion. A SQL default is not data backfill or codec migration. |
| Index/CHECK evolution | Named whole-column index additions/removals and bounded named table-CHECK additions/removals. Construction declarations can have different admission limits; admitting a CREATE fact does not authorize altering it. |
| Ownership lifecycle | Whole-table relinquishment on both backends, strict initial SQLite adoption and later strict re-adoption. No native adoption, column-level adoption/relinquishment, partial-table adoption or cross-tool ownership transfer protocol. |
| SQLite preservation | Explicitly reviewed unmanaged preservation through supported rebuilds. Clean adoption remains strict: preserved extra columns/indexes/triggers still prevent re-adoption. Dependencies on removed members stop the transition. |
| Historical deployment | Committed, trusted packages without current model/author/codec imports; supported receipts remain unchanged. No automatic conversion of incompatible experimental or released histories. |

The strict-versus-partial adoption recommendation is therefore **strict for the first
promotion**. The extended ownership journey's re-adoption refusal is a documented limit,
not a bug to bypass with preservation flags. Partial adoption needs a separately chosen proof
and ownership model; it is not a prerequisite for this bounded release.

Opaque codec behavior cannot be recovered from physical storage or an erased annotation.
Use an explicitly supplied historical codec-bearing query declaration or physical-wire adapter
where automatic historical source refuses. A new representation needs new reviewed data work;
unchanged schema digests do not prove codec identity or business correctness.

## Keep the interface small

1. **Author:** generate a draft from recorded intent, name historical checkpoints, use typed
   queries, and compose complete stages. Do not require synthetic revisions or state copying.
2. **Freeze/review:** compile, inspect and persist packages; build explicitly calls
   `Package.check(current_route)`. Loading validates supplied artifacts, not absent source.
3. **Prepare:** inspect target-bound lowering, observations and assumptions without recording
   application. Review and durably retain the original prepared evidence before native apply.
4. **Execute/observe:** explicit apply and status under coordination; status ordering is not a
   portable chronology contract. Ordinary application queries and verification stay separate.
5. **Recover:** inspect the original evidence, then explicitly resume or perform only a proved
   structural reconciliation. Reassess after a competing operator completes; resume is not an
   idempotent apply wrapper. Ambiguous data work remains stopped.

No new CLI, directory discovery, model-registration ownership, general compatibility framework
or parallel convenience facade is proposed. A versioned persistence contract for the existing
prepared evidence is a missing capability, not a reason to expose private lowering helpers.

## Recovery contract and actual evidence

| Situation | Required outcome | Current evidence / limit |
| --- | --- | --- |
| SQLite package failure or DELETE active-process death | Schema/data/new receipt remain atomic; after confirmed rollback use fresh prepare/apply. Competing ordinary appliers recheck under the writer lock. | Actual role-process death and applied/already_applied race demonstrated. Not WAL proof. |
| SQLite WAL active-process death | Same truthful atomic receipt contract, with the actual WAL mode observed. | Actual uncommitted UPDATE-trigger WAL spill, SIGKILL and fresh SAME-original completion demonstrated under both SQLite builds/NORMAL-FULL/normal-lazy. Pinned reader retains old snapshot across fresh COMMIT. Not host/power/storage-loss proof. |
| Native acknowledged work followed by transactional failure | Retain acknowledged progress; inspect original evidence and resume only proven remaining work. | Selected operation tests and real blocked-backfill death demonstrate this; no blanket DDL atomicity. |
| Native restart after client rollback | Durable uncertainty survives; ordinary prepare/apply refuses, explicit inspection/resume is required. | Actual private-server kill/restart and competing resumers demonstrated; loser reassesses status. |
| Native transactional COMMIT request/response loss | Failed await does not prove rollback/completion. Fresh durable marker/data selects ORIGINAL inspection/resume, not replay of committed work. Already-durable complete receipt means already_applied even if the final explicit COMMIT call failed. | Actual first request/OK loss/EOF and final request/OK loss demonstrated on one local build in the [COMMIT checkpoint](recorded-migrations-commit-outcomes-review.md). Not crash/fsync/all-build qualification. |
| Native DDL effect with a missing acknowledgement | Do not infer data execution or authorize replay from a matching endpoint. Prove a supported structural reconciliation explicitly, otherwise remain ambiguous. | Actual role ALTER genuine-OK withholding/EOF demonstrated across all four exact LTS builds/normal-lazy: uncertain2, explicit original reconciliation then finish, no DDL/data replay. Role server kill AFTER rollback is separate evidence, not DDL-loss proof. |
| I/O timeout/cancellation | Preserve known versus unknown outcome evidence and discard unsafe connections; bounded cleanup cannot manufacture rollback or completion. | Owned opening, local/backend coordination, per-I/O/control, context drain and normal close have separate budgets. Native/session/metadata and SQLite file-policy checkpoints are implemented. Real late SQLite COMMIT and native request/reply loss observed. Known retained close is joined with a fresh budget; candidate live-loop/supervision restrictions exclude global task/loop termination with pending physical work. No universal physical-stop guarantee; G5 must approve lifecycle adequacy. |
| Missing/incompatible original plan or ledger | Refuse without receipt rewriting, reconstruction from current models, or endpoint stamping. | Actual old nine-column ledger refusal demonstrated. Original raw Prepared JSON was not versioned; the later version-one envelope is not a ledger backup or cross-version conversion policy. |

[Workflow](recorded-migrations-workflow-review.md),
[ownership](recorded-migrations-ownership-review.md),
[codec evolution](recorded-migrations-evolution-review.md),
[framework evolution](recorded-migrations-framework-evolution-review.md) and
[real recovery](recorded-migrations-recovery-workflow-review.md) retain the visible programs,
committed packages and evidence limits. Their passing examples do not certify every window.

## Five promotion gates, in implementation priority order

### G1 — Version the execution contract, not only operation capabilities

**Recommendation:** start with one explicit execution-contract epoch; preserve its accepted
historical execution identities or explicitly refuse it when compatibility cannot be retained.
An old-epoch reader/validator may be retained deliberately, but automatic conversion is not
required. Package capability versions 2–8 are not that policy.

At the proposal baseline, `Package.load` recompiled with the current public compiler and
preparation used an unversioned lowerer. The follow-through above now selects defined epoch-one
canonical replay and lowering. Frozen bindings alone would not remove either coupling.
The epoch policy must cover compiler AND target-preparation
semantics, without freezing catalog bugs as truth: stronger verification may safely refuse,
but must not reinterpret old receipts as stronger certificates. An incompatible reader must
stop before database mutation, not regenerate packages or rewrite accepted plan identities.

Acceptance: unchanged committed valid references retain their identities; a deliberately
incompatible execution interpretation is dispatched to its supported semantics or refused
explicitly. Include a prepared/deferred-contraction case, not just new operation admission.
Archived capability evolution alone did not provide this guarantee. The later execution-epoch
checkpoint adds actual incompatible current grouping plus an original deferred-plan case for
one supported historical interpretation, with current safety gates still active.

### G2 — Make original prepared evidence a durable interface

Define an explicit version, validation/integrity envelope and import/export contract for the
original target-bound Prepared evidence, including its package, ordered steps, observations
and preservation choices. Bind it to the execution epoch and ledger expectations. Caller-owned
storage must be persisted before apply and treated as sensitive trusted executable input.

Acceptance: a replacement worker reads the retained evidence unchanged and inspects/resumes
supported work; corrupt, incompatible or wrong-target evidence refuses without history
mutation. Do not rebuild the original plan with today's lowerer. The initial raw Pydantic JSON
experiment proved same-host process/restart usability only; the versioned follow-through above
now provides explicit envelope/epoch admission and unchanged original-plan loading. No portable
identity, host/volume-loss or general cross-version promise is inferred. The ledger remains
necessary; original evidence is not a backup or a compiler-compatibility registry.

### G3 — Reconcile migration I/O with runtime policy

Implemented bounded checkpoints share owned/TLS opening, per-I/O/control deadlines, local and
backend coordination, positive native release, native version/strictness/UTC/integrity and
SQLite FK/UTF-8/DELETE-WAL/synchronization admission. Current safety/catalog/recovery gates
remain live; no full ordinary initializer or parallel generic runtime is imported.

The [context-exit policy](recorded-migrations-context-exit-review.md) now stops admission,
drains the active owner under a fresh acquisition budget and closes afterward; expired or
cancelled drain discards and preserves primary errors without cancelling caller tasks. Native
uncertainty is inspected only after actual physical state is observed, using ORIGINAL evidence.
Retained SQLite cleanup still requires a live loop and does not certify process-wide shutdown.

**Candidate budget decision:** retain SEPARATE physical opening, local guard, backend coordination,
per-I/O/control, context drain and physical-close budgets. No implicit cumulative acquire/package/
context timer; caller pauses do not consume later seam budgets. Outer caller cancellation is not
physical-stop/rollback evidence. G5 approval remains necessary, but the engineering choice is no
longer unspecified. No new timeout knob/facade, unsafe cleanup SQL or data replay.

The [metadata prerequisite checkpoint](recorded-migrations-native-metadata-review.md) now
requires direct global/exact-schema SELECT/SHOW VIEW/TRIGGER/EXECUTE coverage before native yield,
with byte-exact authenticated principal/schema matching, or explicitly observed server grant
bypass/unrestricted metadata. This does not enable bypass or approve its security posture.
Roles/table/column grants alone refuse.
Candidate prerequisite decision: finite admission plus stable caller-owned authorization/writer
exclusion, NOT a general DDL/engine/storage/readiness audit, privilege repair or revocation fencing.
Actual hidden routine/MyISAM objects refuse before original role work; proper authority reveals
existing obstacles and preserves original recovery rather than certifies readiness.

The [real COMMIT checkpoint](recorded-migrations-commit-outcomes-review.md) now demonstrates
transactional request/actual-OK loss and EOF: fresh ORIGINAL marker0/1 recovery skips committed
work, while final explicit COMMIT failure can follow already-durable complete3. Candidate
outcome policy keeps caller knowledge, per-unit durable markers, completion and cleanup separate;
no whole-Target outcome flag or automatic replay. Existing runtime already passed; no fake fix.

The [retained-cleanup checkpoint](recorded-migrations-retained-cleanup-review.md) now joins a
Target's known SQLite close under fresh operation_timeout even after I/O invalidation. Normal
successful exit observes that close result; expiry/cancellation retains physical ownership and
preserves primary failures. Actual busy-worker journeys distinguish caller return from physical
cleanup, followed by fresh ORIGINAL application and ordinary typed use.

**Candidate G3 policy checkpoint recorded within explicit limits:** caller keeps default asyncio
loop alive until retained physical work settles, owns its tasks/blockers/process supervision and
original evidence. No global drain/supervisor is added; an abandoned opening never yielded Target
and is NOT joined by another Target's exit. Global all-task cancellation/loop termination with
pending physical work, failed-close recovery and guaranteed library cleanup under host/process
death are outside first-promotion qualification, not silently handled. Selected G4 database
outcomes after client death are separate from graceful/global cleanup guarantees. G5 must approve or reject these lifecycle restrictions and
may require a separately designed interface before promotion. G3 engineering choices are no
longer unspecified; this is NOT release acceptance or excluded-shutdown qualification.
Qualification stays finite through public journeys/independent real observations, consistent
with [ADR0017](../adr/0017-per-operation-deadlines-fail-closed.md); not all failure permutations.

### G4 — Qualify the finite environment/recovery matrix

The [WAL process-death checkpoint](recorded-migrations-wal-interruption-review.md) now qualifies
selected local normal/FULL uncommitted role UPDATE-trigger spill, actual SIGKILL, fresh atomic
no003/all earlier own receipts intact, SAME original completion and current typed use. Pinned
WAL readers retain old snapshots while fresh writer commits. Actual checksum-validated spill
proves data work, not BEGIN waiting/DELETE-journal behavior; production runtime already passed.
This is local SQLite3.53.1 process-death evidence, NOT maintained3.45.1/other filesystems,
power/host/fsync/lost-ledger qualification. The [G4 review](recorded-migrations-g4-qualification-review.md)
adds both SQLite builds plus actual native ALTER OK loss across the finite LTS matrix; current
completion/broad-validation status and exclusions are recorded there.

**G4 complete for the explicit finite candidate (2026-10-26):** selected role author/review/
model-free deploy/current-app, ownership/codec/refusal/handoff, WAL process death and actual
native ALTER OK-loss reconciliation now pass all12 normal/lazy environment rows/148 cases.
Real DDL OK withholding/EOF proves uncertain2→explicit original structural reconciliation→finish,
without DDL/data replay. This validates honest stopped outcomes, not every crash permutation,
automatic repair or a general upgrade/host-loss certificate. The maintained selection and exact
builds are in `tests/experimental/qualification-matrix.json`; repeat it when maintaining that set.
At26c61c7,953+953 experimental/1784fast/157+157focused/old-floor1+1 also passed. The later
G5 lifetime source is separately requalified and accepted in the linked G5 review.

Keep isolated owned processes, real models/generated historical source and unchanged committed
artifacts. Normal/lazy modes, exact environment records, completed reports and cleanup evidence
are required. Neither pending CI nor the existing released SQLite environment jobs discharge
this gate. Do not expand unrelated parsers unless a selected supported journey requires it.

### G5 — Interface, ADR and first-promotion scope accepted

The [G5 decision](recorded-migrations-g5-decision-review.md) accepts the existing opt-in
`snekql.experimental.migrations` names plus explicit `Connection.wait_closed` lifetime access,
ADR0023 and the affected older amendments, finite qualification and raw/recorded coexistence.
The released raw-SQL interface stays supported/unchanged; first promotion uses separate targets,
not mixed ledgers/locks, conversion or automatic cutover. Mapping stays independent, initialization
schema-free, readiness separate. Existing explicit model-construction approval remains separate,
not implemented or rescinded and never reconciled through stamping.

Measured repeated declarations/historical-source lifecycle and explicit build freshness are
accepted costs of this finite workflow; Draft.advance already removes manual lineage stitching.
No new CLI, generic supervisor or speculative parser expansion. The previously unobservable
abandoned-opening limitation is NOT accepted as the public interface: B supplies a handle BEFORE
opening and bounded own-cleanup joins after failure/exit, on a live owning loop.

G5 is GO for a bounded opt-in experimental first promotion, NOT a stable raw-runner replacement,
future namespace move or approval to merge/tag/publish. Consumer/release guides and packaging
follow this accepted contract before publication; choose a version only in an explicit release.

## Deliberately outside this candidate

General SQL equivalence/dependency reconstruction; full parent-key/index/type/collation/FK
readiness; arbitrary codecs or semantic data proofs; multiple heads; native/partial adoption;
noncooperating writer fencing and zero-downtime old-writer safety; automatic repair or
retrospective certification; arbitrary history conversion; portable host-loss recovery;
whole-program memory/CPU/I/O budgets and general resumable jobs. Existing bounded package,
SQL and expression limits stay enforced, but are not total-work guarantees.

Security/dependency alerts are separate maintenance work. These exclusions do not weaken
existing safety checks or justify claiming an unverified supported fact. Next follow-through is consumer/release documentation and packaging against the accepted
contract, not unsupported future epochs or attribute-by-attribute verifier expansion. Release
execution remains separately authorized; chronological checkpoints below retain their own limits.

## SQLite writer coordination follow-through

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

## Positive bounded native release follow-through

The [native release checkpoint](recorded-migrations-native-release-review.md) tracks acquired
coordination scopes and positively drains ONLY that native advisory name within a fresh
release-control operation budget. Actual server bootstrap recursion no longer leaks ownership;
primary refusals survive, unrelated names remain owned, and postcommit release expiry closes
the target without undoing acknowledged receipts. Fresh ORIGINAL evidence observes already_
applied after independent session disappearance. No cumulative package clock or automatic
replay. Remaining native prerequisites/admission/outcome/shutdown policy and G4/G5 stay open.

## Inherited native strictness follow-through

The [strictness checkpoint](recorded-migrations-native-strictness-review.md) moves the existing
InnoDB strict-mode prerequisite to admission as well as retaining the live required-column
check. Verify inherited STRICT_TRANS_TABLES or STRICT_ALL_TABLES without rewriting sql_mode;
weak sessions refuse BEFORE yield/original-role execution, and NO_BACKSLASH_ESCAPES remains in
actual execution evidence. Ordinary all-table normalization is unchanged. No old receipt/data
repair or new artifact/epoch/layout. Remaining native version/metadata/other prerequisites,
admission/outcome/shutdown policy and G4/G5 remain open.

## Shared native version follow-through

The [version checkpoint](recorded-migrations-native-version-review.md) uses the existing
ordinary MariaDB identity/minimum10.11 verifier through owned target I/O BEFORE policy/yield.
Actual10.10.7 refuses without schema/data/history mutation; installed positive server retains
original-role/current typed use/exact VERSION observations and unowned data. No fake server,
new parser, minimum change, old receipt conversion or positive LTS/matrix/upgrade qualification.
Remaining G3 metadata/other prerequisites/admission/outcome/shutdown policy and G4/G5 stay open.

## Finite G4 qualification follow-through

The [G4 qualification record](recorded-migrations-g4-qualification-review.md) defines the maintained
exact-build normal/lazy selection and actual native ALTER OK-loss recovery, complementing WAL
process death. `tests/experimental/qualification-matrix.json` keeps that set explicit; tests
select only verified external installations, with no production environment selector/download.
Completed stable-source matrix/broad reports now discharge G4 for that explicit finite set;
G5 approval/consumer guides/merge/release remain separate. See that record for completed counts
and exclusions. Earlier follow-through paragraphs are chronological checkpoint evidence.
