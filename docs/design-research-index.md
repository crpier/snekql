# Design research inventory — 2026-11-08

**Status:** Consolidated evidence inventory for #603/#604. On 2026-11-08, the
maintainer authorized retiring the nine related research drafts. All nine were
archived and **closed without merging**, with comments pointing to #604. Read the
[design checkpoint](design-checkpoint.md) for current decisions and the
[design brief](design-brief.md) for higher-level goals.

GitHub PR state and head commits were queried with `gh` before closure on 2026-11-08.
The OPEN/draft snapshots below are historical capture metadata, **not current state**.
Closure was verified separately in the [retirement record](design-evidence/pr-snapshots/retirement.json).
Reports are linked at recorded commits, not mutable branches. Historical validation
results were not rerun by this consolidation. Branches remain intact. Subsequently,
the maintainer also authorized closing completed research/documentation issues #588,
#590, #593, #596, #599 and #601; see the
[issue retirement record](design-evidence/pr-snapshots/issue-retirement.json).
Migration PR #476 remains separate and open.

## Preservation policy

The checkpoint preserves current reasoning in the repository. The
[evidence capsules](design-evidence/README.md) preserve concrete scenarios, known gaps
and convenient #595/#602 fixtures. The [complete archive](design-evidence/pr-snapshots/README.md)
now preserves all **90 changed files**, plus each PR's pre-closure metadata/body,
with original commits/paths and SHA-256 records. Every archived file was compared
with its original git blob before closure.

The nine drafts were closed only after this archive was pushed to #604. No experimental
code was merged into the runtime or supported test suite. Old reports remain historical;
their recommendations don't override later maintainer decisions. The per-PR disposition
notes explain why each draft was retired, not proposals to close still-open PRs.

No branches were deleted. The six completed research/documentation issues were closed
only after preserving their original context and recording their bounded completion.
Defaults issue #473 and ergonomics issue #474 remain open for unresolved design work;
#603 remains open while #604 awaits review/merge. Other issues were not retired.
Existing issue assignments and claims must be checked before any future implementation.

## Defaults and nullability

### [#539 — Research default declaration typing](https://github.com/crpier/snekql/pull/539)

**Snapshot:** OPEN, draft. Head `851a6447838b8fcb4079649e08f2dd191a60dae8`.

[Recorded report](https://github.com/crpier/snekql/blob/851a6447838b8fcb4079649e08f2dd191a60dae8/research/defaults_473/README.md).

**Preserve:** scenario-first visual comparisons, the eleven-scenario review sheet,
negative/nonsensical declaration checks, native omission experiments and their limits.
The evidence capsule retains the scenario matrix and concrete accepted-gap examples;
224 reported tests included 214 paired static checks and ten parser rejection cases,
not 224 runtime/backend cases.
Separately retain evidence of the callable-intersection omission workaround and its
required-input trade-off. It is relevant to the next declaration comparison.

**Superseded/not selected:** the generated-signature left/right design, recommendation
to keep the current API unchanged, and any treatment of independent defaults as
inherently invalid. Prefixes and selectors are comparison evidence, not selected APIs.

**Disposition:** closed as consolidated research after preserving all changed files,
including the review criteria and runnable omission controls. Candidate declarations
were not merged. Exact replacement defaults syntax is still open.

### [#583 — Research nullability and input/read contracts](https://github.com/crpier/snekql/pull/583)

**Snapshot:** OPEN, draft. Head `84e79599283a844b5515f670327ab838539220ec`.

[Recorded report](https://github.com/crpier/snekql/blob/84e79599283a844b5515f670327ab838539220ec/research/nullability_473/README.md).

**Preserve:** separation of constructor presence, accepted input, successful read and
physical NULL permission; strict application subsets over nullable storage; static
controls distinguishing nominal types from metadata-only assertions.

**Not selected:** independent input/read generics, explicit-only SQL nullability,
Django-inspired defaults or required=True as the final interface. The 18 reported
paired tests also exposed accepted mismatches and over-rejection of a valid schema-
only NULL fallback; the evidence capsule preserves that distinction.

**Disposition:** closed after archiving its complete changed-file set. Use the scenario
matrix alongside #539 for a future declaration decision, not as a selected implementation.

## Purpose and existing behavior

### [#589 — Draft snekql purpose and interface design brief (#588)](https://github.com/crpier/snekql/pull/589)

**Snapshot:** MERGED on 2026-10-31. PR head `b3b4828aa4f27464ea2fcd06a2e412412c5ab13f`.

**Preserved in main:** [design brief](design-brief.md). The default-path/customization
refinement is included. This is the goals document, not evidence all derived proposals
or new runtime contracts were implemented. Nothing to retire.

### [#592 — Assess query-result contracts and decoding policy (#590)](https://github.com/crpier/snekql/pull/592)

**Snapshot:** OPEN, draft. Head `0724c6ae74321e60d510431bf9b72643a61e3477`.

[Recorded report](https://github.com/crpier/snekql/blob/0724c6ae74321e60d510431bf9b72643a61e3477/research/query_result_contracts/README.md).

**Preserve:** the audit that existing column, named/raw and construction paths apply
different policies; useful existing NULL/join/RETURNING/unchecked behavior to preserve.
It explains why a final strict validator alone cannot undo earlier implicit decoding.

**Limit:** source assessment, not a new runtime implementation or a permanent inventory
of current code. Recheck changed paths before implementation.

**Disposition:** closed as a consolidated assessment; its complete report is archived
as historical implementation-planning evidence.

## Pydantic policy and unchecked results

### [#594 — Research per-operation Pydantic validation and driver-value reads](https://github.com/crpier/snekql/pull/594)

**Snapshot:** OPEN, draft. Head `7cb258bf26bc4ed7829a30fc007fe8a7060cc433`.

[Recorded report](https://github.com/crpier/snekql/blob/7cb258bf26bc4ed7829a30fc007fe8a7060cc433/research/pydantic_operation_policy/README.md).

**Preserve:** source/upstream-test evidence for strict=None versus True versus False
precedence, explicit StrictInt relaxation under forced False, and the distinction
between lax validation and bypass. This PR itself did not execute local probes.

**Later decision:** three modes, not four. Declared mode respects explicit strict
annotations; no forced-lax public mode was selected. Whole-operation scope first.

**Disposition:** closed after preserving its full report. Its older menu of unresolved
options does not override later mode decisions.

### [#595 — Prove zero-wrapper Unparsed values through direct TypeAdapter validation](https://github.com/crpier/snekql/pull/595)

**Snapshot:** OPEN, draft. Head `2f8206dd0062afb516c46017899b0c84f8f0a194`.

[Recorded report](https://github.com/crpier/snekql/blob/2f8206dd0062afb516c46017899b0c84f8f0a194/research/unparsed_593/README.md).

**Preserve:** scalar runtime identity plus positive/negative checker evidence; direct
TypeAdapter validation establishes its selected target type. Raw values don't carry
their erased type argument or the complete original contract at runtime.

**Limit:** no complete structured-result materialization, automatic adapter inference,
generic Unparsed[T]→T parser or safe model revalidation proof. The later choice is a
marker per complete result, preserving list/cardinality structure.

**Disposition:** closed after archiving the full changed-file set. The
[proof and harness](design-evidence/README.md) remain convenient evidence entry points;
no incomplete raw-results feature was merged.

## Attribute and construction/read experiments

### [#597 — Evaluate Pydantic-owned attribute contracts for trustworthy reads](https://github.com/crpier/snekql/pull/597)

**Snapshot:** OPEN, draft. Head `f8902a2e7e2addb8e1a97665a3ac544d8472fe66`.

[Recorded report](https://github.com/crpier/snekql/blob/f8902a2e7e2addb8e1a97665a3ac544d8472fe66/research/attribute_contracts_596/README.md).

**Preserve:** executed synthetic representation/strictness examples for int, bool,
date, UUID and JSON; source-inspected driver forms; separation of parsing success from
correct SQL comparison/storage representation.

**Limit:** synthetic inputs are not newly executed backend queries. Helper contracts in
the report are not new public types or a selected automatic-decoding policy.

**Disposition:** closed after archiving the full report, fixtures and controls. Reuse
appropriate controls when implementing the direct-driver boundary.

### [#598 — Compare construction and SQL read contracts without duplicate logical rules](https://github.com/crpier/snekql/pull/598)

**Snapshot:** OPEN, draft. Head `64c7d1549dc648337e5d1a70fb4cde7f2720ae8e`.

[Recorded report](https://github.com/crpier/snekql/blob/64c7d1549dc648337e5d1a70fb4cde7f2720ae8e/research/input_read_596/README.md).

**Preserve:** reuse of complete constraints/validators, JSON entry-point differences,
non-idempotent-validator controls and the danger of a global read-phase flag leaking
into nested JSON validation.

**Superseded/not selected:** ReadInput was illustrative, never a chosen API. The later
explicit driver→Pydantic decision forbids inserting a competing hidden pre-decoder.
The construction/JSON boundary still needs a concrete design.

**Disposition:** closed as comparison research after archiving all changed files and
counterexamples. The favored adapter direction was not merged as a selected interface.

## Precision and static operation restrictions

### [#600 — Research explicit precision-loss protection (#599)](https://github.com/crpier/snekql/pull/600)

**Snapshot:** OPEN, draft. Head `c526cf13b3fefb790f758a0ae58f838be2dec492`.

[Recorded report](https://github.com/crpier/snekql/blob/c526cf13b3fefb790f758a0ae58f838be2dec492/research/precision_loss_599/README.md).

**Preserve:** 30 focused Pydantic cases; built-in decimal constraints accept harmless
trailing zeros and reject tested nonfits; explicit datetime rejection; custom
serializer gap; exact text versus float behavior; existing encode-fit checks audit.

The preceding ORM research inspected SQLAlchemy, Django, Prisma and Rails documentation
and source. None established a universal lossless-write guarantee. Some validate only
when requested; Rails also silently normalizes values. Strict modes and warning
inspection are incomplete. This was not a native cross-ORM/database benchmark.

**Superseded:** additional final-parameter checking was subsequently rejected as a new
runtime layer. Integer-minor-unit versus text recipes were challenged as an unsatisfying
single-type experience. The report does not select SQLite's decimal mapping. Existing
encode checks are compatibility facts, not a requirement to keep that architecture.

**Disposition:** closed after archiving the complete experiment, including existing-type
and serializer counterexamples. Its rejected checking hooks remain historical text,
not production safeguards.

### [#602 — Research static rejection of ZonedDatetime ordering with ty (#601)](https://github.com/crpier/snekql/pull/602)

**Snapshot:** OPEN, draft. Head `e3a9310aa88f3f674b3ed48eba1562eecf44ee6c`.

[Recorded report and replay instructions](https://github.com/crpier/snekql/blob/e3a9310aa88f3f674b3ed48eba1562eecf44ee6c/research/static_ordering_601/README.md).

**Preserve:** replayable test-first, real-package temporary-source proof. Baseline
misses 13 forbidden calls; the restricted consumer diagnoses all 20 marked negative
sites while positive examples pass. Parent replay confirmed the change. The second
restricted-self/Python-ordering proof is useful corroboration, not a storage policy.

**Later clarification:** ty is the intended checker; experimental ty features and
lack of multi-checker portability aren't blockers by themselves. Runtime annotation
handling and maintenance still need assessment. Generic helper constraints and uncovered
column/aggregate/derived-query seams remain real limits.

**Not proven:** general type-plus-storage capabilities, arbitrary Annotated markers,
complete static enforcement or permission to remove all runtime checks immediately.

**Disposition:** closed after archiving the complete changed-file set. The
[ty replay fixtures](design-evidence/README.md) and known-hole controls remain accessible;
experimental overlay patches were not applied to production.

## Separate work: don't absorb or retire it here

[#476 — Run async Python migrations with revision identity](https://github.com/crpier/snekql/pull/476)
was also OPEN/draft in the snapshot. It is separate migration implementation work,
not one of these interface-research drafts. This consolidation makes no merge/close,
assignment, authority or implementation recommendation for it.

## What is preserved without merging the drafts

The checkpoint records the actual directions and rejected approaches, the evidence
capsules retain concrete examples, and the full per-PR archive preserves all changed
files and pre-closure metadata. Commit-pinned reports retain external provenance too.
This avoids treating retired draft branches as competing specifications. Preservation
is part of #604, not yet merged into main; archived sources are not supported runtime
modules or automatically maintained tests. Future branch/issue cleanup requires its
own authorization.
