# Recorded ownership is independent of query mapping

Status: **Proposed** for #477 / draft PR #482; not a supersession of released interfaces.

The role-transition, ownership and historical-evolution journeys demonstrate why query
mapping cannot also select migration ownership: an application can query an external table,
keep querying a relinquished table, or change codecs without changing the physical schema.
Propose an explicitly selected recorded-state chain, editable typed transitions and frozen
model-free execution packages, rather than making current application models the deploy-time
schema authority. The cost is a versioned execution/recovery contract and explicit authoring
freshness; package hashes alone do not remove compiler or preparation coupling.

## Proposed decision

- Keep query mapping, migration ownership and application readiness independent. Ownership
  selects the physical facts a chain can claim or alter, not query access or codec correctness.
- Generate against previous recorded intent, not an incidental developer database. Named
  intermediate query contracts support typed data work; complete stages retain real lineage.
- Deploy committed packages without current authoring/models. Prepare explicitly against the
  target, then apply under coordination with durable, truthful progress. Preserve the original
  prepared evidence; uncertain data execution is not permission to replay.
- Recommend strict SQLite adoption, bounded preservation and whole-table relinquishment for
  the first promotion. Preservation is not partial adoption, and relinquishment is not DROP.
- Version execution interpretation, including deferred preparation, separately from operation
  capabilities. Preserve supported identities or refuse incompatibility; do not regenerate
  historical artifacts, rewrite receipts or silently certify an old outcome more strongly.
- Keep incompatible writers excluded by caller policy. Advisory locks are coordination, not
  application quiescence or fencing. Structural verification/history are not readiness proofs.

The [supported-scope proposal](../proposals/recorded-migrations-supported-scope.md) specifies
candidate environments, explicit exclusions and promotion gates. Execution-epoch design,
prepared persistence, deadline/session integration and remaining qualification are **not
implemented by this ADR**. It authorizes no release or consumer-interface replacement.

## Reconcile rather than silently supersede

| Existing decision | What remains / what needs an explicit amendment at promotion |
| --- | --- |
| [0001: hand-authored raw SQL](0001-hand-authored-raw-sql-migrations.md) | Reviewed explicit application and historical authority remain. The prohibition on generation would change for the recorded interface; released raw-SQL behavior and any coexistence/cutover policy need a separate explicit decision. |
| [0002: migration coordination](0002-advisory-locked-concurrent-migrations.md) | Retain SQLite writer coordination/native advisory locking and under-lock history rechecks. Do not extend these to schema-writer exclusion, application pause or general retry safety. |
| [0007: connect-only initialization](0007-imperative-migrations-connect-only-initialization.md) | Retain non-mutating initialization and explicit deployment. Revisit the live-Database-only deployment interface for the dedicated model-free target. Reconcile separately approved explicit model construction separately; neither model generation nor this proposal reintroduces boot-time creation or history stamping. |
| [0008: partial structural verification](0008-separate-partial-schema-verification.md) | Retain separate partial application-model verification. Recorded ownership/postcondition checks have different obligations; neither is a full data/codec/session/query-readiness certificate. Amend the hand-authored-only rationale if promoted, not its partiality into equality. |
| [0003: backend declarations](0003-per-backend-namespace-column-declarations.md), [0005: storage and codecs](0005-storage-primitive-constructors-with-derived-codecs.md) | Retain backend-specific physical declarations and the distinction between logical type, codec and storage. Opaque annotations/storage hints cannot recover erased codec provenance. |
| [0013: query execution plans](0013-execution-plans-own-runtime-policy.md) | Private query execution plans and public target-bound migration prepared plans are different contracts. Share appropriate runtime policy, not their identities or result semantics. |
| [0017: fail-closed deadlines](0017-per-operation-deadlines-fail-closed.md) | No migration exemption. Direct experimental driver calls are an integration gap, not evidence that a Config's deadlines/session policy are honored. Preserve outcome knowledge and discard unsafe connections. |
| [0018: reviewed baseline, no stamping](0018-reviewed-baselines-without-history-stamping.md) | Retain no manufactured earlier history. Explicit SQLite adoption records a newly proved ownership claim, not proof of earlier data work or conversion of a deployed chain. |

## Alternatives and consequence

Inferring ownership from query models would erase query-only external mappings and make
relinquishment break ordinary use. Depending on current models/codecs at deployment would
reinterpret history; keeping only handwritten SQL would retain the measured creation and
staged typed-backfill friction. Broad SQL reconstruction or partial adoption would enlarge
the initial proof obligation without completing this workflow.

The proposed smaller scope accepts strict refusals and explicit maintenance windows. Its
costs must remain visible: author/build freshness is deliberate, historical codec declarations
can be explicit, original recovery evidence needs durable storage, and unknown effects can
require stopping for separately designed recovery. Until these contracts and qualification
are accepted, existing ADRs remain in force and the prototype stays experimental.
