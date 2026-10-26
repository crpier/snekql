# Recorded migrations: G5 interface and promotion decision (#477)

Status: **G5 engineering contract accepted** (2026-10-27), after final-source requalification.
This is engineering scope acceptance, not merge/tag/publication or consumer-guide completion.
The maintainer selected **B: explicit connection lifetime ownership**, rather than making
supervised subprocesses the only supported deployment topology.

## Decision, names and interface

Keep the qualified opt-in namespace **`snekql.experimental.migrations`** for the first bounded
promotion. Do not add a competing `snekql.migrations` facade, rename the released Database verbs,
or imply that this promotion freezes every exposed prototype detail forever. Architectural
acceptance, a maintained finite execution contract and removal of the experimental namespace
are different decisions; a later stable-namespace move requires its own compatibility review.

The selected interface is the existing workflow, plus the approved lifetime seam:

| Role | Names and obligations |
| --- | --- |
| Author | `generate`, immutable `Draft.then/resolve/adopt/advance`, explicit `Checkpoint` and typed `DataChange.from_query`. Desired model lists select ownership, not query mapping. |
| Historical queries | `contract_source` / `contract_digest`; emit and statically import real source. Opaque codecs/names need explicit historical adapters; no inferred codec ABI. |
| Build | `compile`, `Package.check(current_draft)`, `Package.dump/load`; commit reviewed source/artifacts and typecheck. Loading cannot discover authoring that was not supplied. |
| Lifetime | `connect(config) -> Connection`, then `async with lifetime as target`; construction opens nothing. Retain the lifetime BEFORE entry. `wait_closed()` joins its cleanup AFTER failed entry or context exit. |
| Prepare/deploy | `Target.prepare`, inspect `Prepared`, durably retain ORIGINAL `Prepared.dump` before `apply`. Models/authoring are not deploy-time authority. |
| Observe/recover | `status`, `inspect_recovery`, explicit `reconcile(reason=...)`, `resume`; original target-bound evidence, stable visibility and excluded competing writers. No automatic ambiguous-data replay. |
| Application | Ordinary backend queries/partial `verify` remain separate. Completion is not readiness, codec validation or writer fencing. |

`Target` is obtained through the connection lifetime; direct driver/Target construction is not
an alternative admitted deployment interface. State/contraction/step values are inspection and
trusted authoring representations, not an invitation to bypass model-derived generation or
construct history. No migration Python callback, generic raw-SQL runner, new CLI, retry service,
format registry or supervisor is introduced.

Keep current result/error names and finite recovery dispositions. `Progress.acknowledged_steps`
is durable ledger progress, not receipt of an OK by the original caller; consult the separate
`reconciliations` audit for structurally accepted units. `phase="complete"` does not erase that
distinction. `status()` ordering is unspecified; render it explicitly without using display
ordering as predecessor authority. Existing deadline/acquisition/package errors remain distinct. Ordinary application credentials
need not qualify for dedicated migration metadata authority; deployer and query roles stay separate.

## Why the old lifetime restriction was inadequate

The G3 candidate retained abandoned opening work correctly, but failed SQLite entry yielded no
Target and no public way to observe its cleanup. "Keep the loop alive until done" therefore
required private state or OS observation in ordinary callers. Successful Target exit only joined
that Target's known close, not an opening that never yielded it. G4 proved the physical effects;
it did not make this an adequate general in-process interface.

Reject accepting that unobservable restriction as the public contract. Also reject a global
barrier, registry-wide drain, forced rollback on an interrupted connection, unbounded close wait,
or claiming that task cancellation/shielding makes physical work stop. The chosen small lifetime
module earns its place by representing resource ownership before any opening await.

### Exact `Connection.wait_closed()` contract

- `connect(config)` is inert and returns a **single-use** lifetime. Entry owns opening and
  admission; the existing concise `async with connect(config)` form still works.
- Retain that object when failure handling needs to join physical cleanup. After failed entry
  or exit, `await lifetime.wait_closed()` joins ONLY its retained opening/close producer. It does
  not reopen, admit late package work, reapply, restore unsafe policy or join another lifetime.
- Calling the wait before entry or while the context is active refuses. Exiting before entry
  cannot accidentally open a database. Reentry refuses. Do not concurrently enter/exit the same
  context; concurrent post-exit cleanup waiters are supported.
- Each wait has a **fresh Config.operation_timeout**, reported as `migration close`. Prior
  acquisition/I/O/context time does not consume it. There is no new knob or package-wide timer.
- Deadline/task/scope cancellation of one waiter does NOT cancel the owned producer or other
  waiters. A caller may explicitly wait again after releasing its own blocker. No automatic or
  infinite retry is added. Failed waits do not certify disposal.
- Successful wait observes this lifetime's known local cleanup result, not instantaneous OS
  thread/transport-callback scheduling, native server statement termination/rollback, remote
  lock release, global process quiescence or readiness. Native synchronous socket disposal is
  not a remote outcome acknowledgement. Pending joins use the same owning loop, kept live;
  global all-task cancellation/loop stop cannot be repaired by a library future. Caller owns its active tasks, authorization and writer policy.
- A primary context body error/cancellation still wins over secondary context cleanup failure.
  A later explicit wait observes the cleanup producer's outcome; a failed producer is never
  turned into success or automatically retried/replaced. Observed non-task cleanup failures are
  retained too. General failed physical-close recovery remains unqualified, not silently fixed.

The factory/context shape is already exercised by standalone actual programs. The changed
implementation shares the existing fresh close-join policy; opening retention remains owned
per lifetime even though the existing internal retention set prevents abandoned owners' GC.
That set is not a public drain or a barrier over unrelated databases.

## Authoring ergonomics accepted, not hidden

`Draft.advance` removes manual state/lineage stitching within one revision. Retain explicit
intermediate declarations and generated query source: they express meaningful historical
shapes. The measured repetition is acceptable for this finite interface; no speculative model
factory or live-database diff is required to promote it.

The build must regenerate historical source when its named contract changes, typecheck the
actual author program, and check the compiled package against the completed current route.
A data-only edit can change frozen bindings while the schema digest stays equal. Review both;
no model import during deployment can substitute for that build check. Commit historical
artifacts and do not regenerate them to accommodate a new interpreter/compiler.

Opaque application codec changes require explicit historical declarations and, when needed,
a reviewed representation migration. Ordinary structural verification may pass while decoding
fails. Preserve this honest separation rather than attach a false codec/readiness certificate
to the recorded schema.

## Released/recorded coexistence and cutover

Keep released `db.migrate(MIGRATIONS)` / `db.verify_migrations(MIGRATIONS)` supported and unchanged;
no deprecation/removal version is selected. Recorded chains are opt-in, not a new interpretation
of raw-SQL bodies or the `snekql_migrations` ledger. Their dedicated ledger and advisory names
are not a shared ordering or lock domain with the released runner.

First promotion uses **separate deployment targets for the two runner families**. This is a
caller-owned deployment precondition, not a claimed universal mixed-history detector. Never
schedule both authorities against one target or assume their locks coordinate each other.
Presence/matching schema/partial verify/raw history is NOT a recorded receipt or implicit stamp.
Do not delete history to make a target appear new.

No raw→recorded conversion, canonical-chain replacement, old-ledger conversion or automatic
cutover is approved here. If a deployed application later needs one, design and test a specific
offline transition with preserved evidence and one explicit authority. Strict initial SQLite
adoption proves newly claimed structure only; it is not a backdoor for certifying previous data
work. Native/partial adoption stays unsupported. Existing direct model-construction approval
remains separate: nothing here implements, revokes or silently reconciles it by stamping.

## ADR and first-promotion scope

Accept ADR0023 with the completed new-source evidence below; explicitly amend0001/0002/
0007/0008/0017/0018 rather than silently treating older raw-only/Database-only statements as if
they already described this workflow. Preserve backend declarations/codecs0003/0005, private
query-plan policy0013 and temporal0022. Mapping/ownership/readiness remain independent.

Accept only the finite environment set maintained by `qualification-matrix.json`, expanded to
exercise the new lifetime on both actual SQLite builds/modes and normal native use. Keep formats
2–8/epoch1/Prepared wire1 under their defined supported interpretation or explicit refusal;
no automatic conversion or retrospective receipt upgrade. Strict adoption, preservation,
whole-table relinquishment, stable metadata authority, caller writer exclusion and original
plan retention remain requirements. Exact build qualification is not every patch, platform,
TLS/transport/ABI/engine-upgrade or host/power/volume-loss support.

Consumer documentation/release packaging must follow this accepted contract before publication;
this engineering record is not a consumer guide. No merge, tag, version or publication is
requested or authorized. Dependency maintenance and #473/#474 remain separate.

## Evidence admission

New TDD reports and final-source requalification live under `.snektest/477-g5/`.
Opening RED: the old returned context has no `wait_closed`; real lease/late handle still owned.
Retained-close RED: an opening-only lifetime falsely returned success while its busy worker was
still blocked. Ordering RED: invalid exit raised an underlying generator RuntimeError rather than PackageError;
the lifetime now rejects it before opening. The latter two are intermediate G5 implementation
failures, not defects attributed to the qualified G4 runtime.
These are three actual development slices, not claims that G4 demonstrated corruption or that
all unchanged runtime behavior needed a fabricated failure.

The real lease operator now tests fresh join expiry BEFORE lease release, cancelled waiters,
unrelated lifetime completion without draining the abandoned opening, and explicit successful
join/idempotence before independent worker/FD observations and frozen-role/current typed use.
Busy-worker finish/deadline/primary/task/scope cases additionally test bounded post-exit joins,
concurrent waiters and cancellation isolation, physical disposal, unchanged OWN receipts and
SAME original completion. Native partial-opening tests join their lifetime and independently
observe peer EOF; native ordinary completion/closed-target rejection is exercised too.

The completed final matrix/broad counts below qualify this changed source. The original G4
reports remain valid for26c61c7, not its automatic validation. Failed/incomplete setup reports
remain excluded and retained. Exact committed-source readback is retained with local evidence.

One expanded-matrix setup miss is preserved under `before-opening-pythonpath/`: eight native
rows completed, then SQLite3.45.1 reported21passed/3child-start timeouts. The old opening harness
replaced inherited PYTHONPATH with the project root, dropping the externally built interpreter's
selected dependency site-packages from its child environment. An exact child dependency probe
shows `ModuleNotFoundError: anyio`; preserving inherited paths makes all three opening cases pass.
This is a harness correction, not a migration runtime RED. Its Python source change requires a
NEW frozen-source full matrix/broad run; earlier completed rows are not counted in final totals.
A cache copy named `operator.py` also shadowed the stdlib during initial verifier startup;
rename the EXTERNAL copy, retain the setup report. No production behavior is inferred from it.

## Final G5 admission (2026-10-27)

**GO for the bounded opt-in experimental first-promotion contract; not approval of a stable
replacement for released raw SQL, a future namespace move, merge or publication.** B supplies
an observable in-process lifetime instead of a subprocess-only restriction. Names/ergonomics,
ADR0023 and explicit older amendments, separate-target coexistence/no cutover and finite scope
are accepted together. G1/G2/G3 decisions and G4 qualification remain within their explicit limits.

Completed stable-source evidence:

- **956 normal +956 forced-lazy experimental**, **1784 fast**, **160+160 focused**; actual10.10.7
  negative **1+1** separately. Zero failures/errors/fixture/session teardown failures throughout.
- Expanded matrix **216 cases /12 completed environment/mode rows**: eight native15-case rows,
  four SQLite24-case rows. Ancillary paired-backend cases are not extra maintained targets.
- **Six public lifetime operator traces**, **20 real DDL-loss traces**, **four final WAL traces**;
  real wait channels/worker/FD/process observations, originals0600 and frozen current-app use.
- Whole-tree ty/ruff/format689/diff and generated-overload check pass; standalone actual operator
  type/lint checks pass using test profile + INP001-only executable exception.
- **570 Python/program hashes** frozen; **69 historical artifacts unchanged**. Exactly TWO
  production modules change from26c61c7: lifetime implementation and its lazy public re-export.
  No package format, epoch, ledger, declaration, dependency or ordinary runtime change.
- Final source/provenance/links and actual owned-server audit admitted; all validation runners
  finished. Evidence `.snektest/477-g5/`; failed/setup/development reports preserved separately.
  No Actions requested/polled/awaited, no consumer guide promotion or release claim.

Next is consumer/release documentation and packaging follow-through against THIS accepted
contract, before any publication. No need to reopen the resolved lifecycle/name/coexistence
choices or resume speculative parser work. Stable-namespace promotion and any deployed-history
cutover would be explicit later decisions, not promised compatibility or automatic conversion.
