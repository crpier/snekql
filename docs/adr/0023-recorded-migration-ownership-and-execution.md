# Recorded ownership is independent of query mapping

Status: **Accepted for the bounded opt-in first-promotion design** (2026-10-27), #477 / PR #482.
The maintainer selected explicit connection lifetime ownership (B); completed new-source
qualification is recorded in the G5 review. No merge, stable-namespace move or publication.

Choose an opt-in recorded-state chain, editable typed transitions and frozen model-free
execution packages. Query mapping cannot also select migration ownership: an application can
query external or relinquished tables and change codecs without changing physical schema.
Compared with handwritten-only migration bodies, this removes measured staged-authoring and
rebuild bookkeeping at the cost of explicit build freshness and a versioned execution/recovery
contract. It is a recorded-intent diff, not a live-developer-database diff.

## Decision

- Keep query mapping, migration ownership and application readiness independent. Desired model
  lists explicitly select managed facts; querying never acquires ownership. Recorded completion
  and partial application-model verification are not codec/data/session/readiness certificates.
- Generate against previous recorded intent. Author explicit immutable stages and named
  intermediate historical typed queries; compile and check the complete reviewed route.
  Deployment imports packages, not current authoring/models/codecs. Historical source and
  scalar bindings remain explicit when opaque codecs cannot be reconstructed honestly.
- Use the existing `snekql.experimental.migrations` names for the first bounded opt-in promotion:
  generate/draft/contract/compile/package, connect/prepare/apply/status and explicit original-plan
  recovery. No second public facade, CLI, callback runner or namespace-stability promise is added.
  Retaining the experimental namespace is deliberate; architectural acceptance is not a future
  stable-namespace move or an indefinite ABI promise for every exposed prototype detail.
- `connect(config)` returns a single-use **Connection lifetime before opening**; async entry
  yields Target. Construction opens nothing. Retain the object for bounded `wait_closed()` after
  failed entry or exit. It joins only its own retained opening/close work, without reopening,
  replay, global drain or unsafe connection SQL. Reject the previous unobservable "keep the
  loop alive until abandoned opening cleanup finishes" restriction as the promoted interface.
- Preserve separate opening, local guard, backend coordination, per-I/O/control, context drain
  and physical-close budgets. Each cleanup wait gets a fresh operation budget; cancellation
  stops that waiter, not its producer or another waiter. Primary body failures win at context
  exit; later explicit joins expose cleanup outcomes. Failed/expired waits do not prove disposal.
  The owning loop must remain live while joining. No global all-task-cancel/loop-stop guarantee,
  generic failed-close repair or physical-stop/rollback inference from deadline/socket return.
- Prepare explicitly against observed targets, review choices and retain ORIGINAL prepared
  evidence durably before apply. Execution epoch1 defines interpretation of admitted formats2–8,
  separately from operation capabilities and Prepared wire1. Preserve supported identities or
  refuse incompatibility; no re-lowering old plans, history conversion or retrospective upgrade.
- Keep strict initial SQLite adoption, bounded preservation and whole-table relinquishment.
  Preservation is not partial adoption; relinquishment is not DROP. Native/partial adoption
  remains unsupported. A new proved structural ownership claim is not earlier data history.
- Coordinate migration work and recheck under coordination, while the caller excludes competing
  schema/incompatible affected-data writers and keeps authorization/metadata visibility stable.
  Advisory locks are not writer fencing, application pause or a privilege-revocation barrier.
- Keep released raw-SQL migration verbs/history unchanged and supported. First promotion uses
  separate deployment targets for raw and recorded runner families; their ledgers/locks are not
  interoperable. This is a caller deployment precondition, not a universal mixed-history detector.
  No chain mixing, implicit stamping, raw-history conversion or automatic cutover is approved.
- Accept only the maintained finite qualification selection and its stated exclusions, not all
  versions/patches/OSs/loops/transports/TLS/ABIs/engine upgrades or host/power/volume-loss recovery.

## Reconciliation of older decisions

| Decision | Explicit scope amendment or retained rule |
| --- | --- |
| [0001: hand-authored raw SQL](0001-hand-authored-raw-sql-migrations.md) | Raw-SQL behavior stays; recorded generation and bounded reviewed rebuilds are an additional opt-in authority, based on recorded intent rather than live diff. Neither runs autonomously. |
| [0002: coordination](0002-advisory-locked-concurrent-migrations.md) | Retain writer/advisory coordination and history rechecks. Recorded SQLite package atomicity/native durable units have their own outcomes; no shared raw/recorded lock or external-writer fencing. |
| [0007: connect-only initialization](0007-imperative-migrations-connect-only-initialization.md) | Initialization remains schema-free. Recorded deployment uses dedicated model-free connection lifetimes, not only a live ordinary Database. Separately approved explicit model construction remains separate; no boot-time creation or stamping. |
| [0008: partial structural verification](0008-separate-partial-schema-verification.md) | Retain separate partial application-model verify; recorded ownership checks have different obligations. Amend hand-authored-only rationale, not partiality into equality/readiness. |
| [0003: backend declarations](0003-per-backend-namespace-column-declarations.md), [0005: storage/codecs](0005-storage-primitive-constructors-with-derived-codecs.md) | Retain backend declarations and logical/codec/storage separation. Opaque metadata cannot recover erased codec provenance. |
| [0013: query plans](0013-execution-plans-own-runtime-policy.md) | Private query plans and target-bound public Prepared evidence remain different contracts. Share appropriate policy, not identity or result semantics. |
| [0017: fail-closed deadlines](0017-per-operation-deadlines-fail-closed.md) | Apply owned deadlines/disposal to recorded connections too. Explicit lifetime joins make retained cleanup observable, without strengthening unknown database outcomes into rollback. |
| [0018: no stamping](0018-reviewed-baselines-without-history-stamping.md) | Retain no manufactured earlier history. Strict initial SQLite adoption is new proved ownership, never conversion/certification of an earlier chain or unacknowledged data work. |
| [0022: temporal meanings](0022-explicit-temporal-meanings.md) | Retain explicit temporal meaning/precision and representation migrations. No automatic data conversion, codec or timestamp recertification. |

## Alternatives and consequences

Reject current models as deployment authority, query mapping as ownership, implicit stamp/
conversion, broad reconstruction/partial adoption, hidden cleanup requirements and a global
process supervisor. Accept explicit review/build freshness, historical declarations, trusted
executable artifacts, retained original evidence and maintenance windows. These are visible
costs, not parser work to expand indefinitely or justification for automatic uncertain replay.

The [G5 decision review](../proposals/recorded-migrations-g5-decision-review.md) records concrete
names, lifecycle semantics, ergonomics, coexistence/cutover and new-source qualification.
The [bounded scope](../proposals/recorded-migrations-supported-scope.md) and maintained matrix
limit first promotion. Consumer/release documentation and packaging follow before publication;
no merge, version, tag or publication is authorized by this architectural decision.
