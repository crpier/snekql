# Recorded migrations: integration and merge review (#477)

Status: **combined-head validation complete; maintainer authorized ready/merge**
(2026-10-27). This does not authorize a version, tag, publication, stable namespace,
raw-history conversion, or a broader runtime certificate.

## Fixed inputs and integration

- Approved consumer/documentation head: `b0cfe6f6ba7fb5307bc871aa1e4b0f1ebfcbccb8`.
- Integrated main: `3ed75324bbb12b189470f296e55faddf63d72b5b`.
- Combined code commit: `d65bffce16ac30f261e217853eb0d87dc1d5bf29`.
- Only manual conflict: `CHANGELOG.md`. Both parents' Unreleased blocks remain
  verbatim; released history matches both parents. API/capability/failure guides
  auto-merge the recorded-family boundaries and main's current query-plan/fault
  coverage. No experimental implementation change is made during integration.

Main brings real query-state, descriptor/codec/decoder/materialization, buffered
SQLite read, FIFO wakeup, query-plan evidence and temporary-server ownership
changes. It also brings the already reviewed security dependency fixes:
certifi 2026.10.23 and OpenTelemetry API/SDK 1.45.1/semantic conventions 0.66b1.
The existing [dependency review](../dependency-reviews/2026-10-25-security.md)
records their upstream/impact decisions; this is not a new upgrade selection.
Lock and published optional minimum are preserved from main, not reverted.

Earlier G4/G5 and [consumer packaging](recorded-migrations-consumer-release-review.md)
reports describe their own checkpoints. In particular, the earlier claim that
all production modules/dependencies were unchanged is **not** evidence about this
integration. Fresh combined-source qualification was required and completed.

## Standards review

Current/incoming AGENTS, contributing guidance, glossary, dependency policy and
accepted G5 constraints were consulted. Work continues this session's #477 claim
on the existing feature branch, with verified assignment/claim. Public seams
remain the previously agreed author/compile/package/prepare/apply/status/recovery,
ordinary typed application, lifetime and installed-resource boundaries.

No manufactured runtime RED, private-helper assertions, callbacks, injected driver
behavior, fixture-state cloning, receipt fabrication or assertion weakening was
introduced. Existing public tests are the integration regressions. The source is
frozen during validation; normal/lazy native work runs sequentially with short
external disk TMPDIRs and context-aware warnings. Detached-driver signal defaults
are explicitly restored for subprocess tests. Manual two-axis integration review
is recorded; no independent parallel sub-agent review is claimed.

Broad staged whitespace diagnostics are retained rather than rewriting evidence:
main already contains archived trace/patch whitespace, independently byte-equal
to main. Feature-versus-main diagnostics identify blank EOF lines in two immutable
format3 JSON fixtures. The scoped source/docs check excludes those two exact
fixtures and passes; all 69 historical artifacts/program references remain
hash-identical. No normalization or retrospective archive repair is performed.

## Spec review

The composed tree retains the bounded experimental design: historical typed
intent and independent frozen interpretation; originals persisted before apply;
truthful durable progress and explicit uncertainty/recovery; separate ownership,
mapping, readiness and physical cleanup; and caller-owned writer/metadata/loop
supervision. Released raw migration APIs remain supported on separate deployment
targets. Unsupported cases refuse; no stable namespace/cutover/general parser,
new timeout knob, CLI or supervisor is introduced.

Actual maintained-build journeys exercise frozen originals, all own earlier
receipt values, real generated contracts, codec replacement, selected physical
interruption/loss outcomes and current ordinary application use. Installed-wheel
recipes additionally prove fresh typing/staleness and model-free deployment,
without source-checkout imports or replacing an existing original.

## Completed current-source validation

Evidence: `.snektest/477-merge/`. **632 program files plus two metadata files**
frozen; **69 immutable historical references** unchanged.

| Check | Completed result |
| --- | --- |
| Full `snektest tests`, normal | 5227 passed; zero failures/errors/fixture/session teardown failures |
| Full `snektest tests`, forced-lazy | 5227 passed; same zero counts |
| Fast suite | 1892 passed |
| Packaging/resource/installed suites | 25 normal + 25 forced-lazy passed, also included in full runs |
| Finite recorded-runtime matrix | 216 cases / 12 environment-mode rows, all passed |
| Installed-wheel recipe matrix | 12 cases / 12 environment-mode rows, all passed |
| Actual 10.10.7 negative admission | 1 normal + 1 forced-lazy passed separately |
| Genuine DDL-loss traces | 20 fresh traces: interrupted-wire cleanup excluded; fresh recovery sessions remain independent |
| Static/build inputs | ty, Ruff lint/format, generated-overload, lock, source freeze and working diff checks passed |
| Standalone lifetime worker | Exact source bytes, explicit typing and repository test-profile lint/format; only executable INP001 exception |
| Artifact smoke | Byte-equal existing script/inputs outside checkout; installed normal/lazy import/runtime/CLI/typing and two actual native driver tests passed |
| Archives | Wheel/sdist/rebuilt wheel inspected; 61 documentation resources, 46 Markdown and 15 recipe sources |

Both matrices use SQLite **3.45.1/3.53.1** and Community MariaDB
**10.11.19/11.4.13/11.8.9/12.3.3**, each normal/all. Native VERSION and actual proc
executable/hash match verified cached binaries; SQLite uses the actual external
or managed engine. No server download, ABI shim, system replacement, production
selector or silent skip. Default 13.0.2 remains regression-only, not an added
maintained positive. Whole-tree results do not certify every platform/build.

The current candidate and sdist-rebuilt wheels have identical SHA-256:
`1e779a4ab8e84fa5c2a74a4be230c5df193f29c60991b027c562ae5561b54187`.
Artifacts remain isolated from the user's `dist/`; metadata stays 0.9.0. They are
not the previously published 0.9.0 bytes and must not be published as that version.
A first optional standalone lint invocation used the ordinary file profile and
reported assertions; it is preserved. The byte-identical worker then passed the
actual test profile via its stdin filename, without source change or a new rule
suppression beyond the existing executable INP001 exception.

## Merge and remaining authority

Ready/merge is authorized only after final source/readbacks, exact remote base/head
and mergeability are verified. Repository policy allows squash only; do not bypass
branch protection or enable auto-merge/Actions to complete this task. If the base
moves, assess and validate the new integration before merging.

The finite exclusions from G5 remain: no all-patch/OS/loop/transport/TLS/ABI/MySQL,
in-place upgrade, host/power/volume loss, all-task-cancel/stopped-loop lifecycle,
general physical-close recovery, native remote-stop/rollback or full readiness
certificate. No Actions request/poll, performance-equivalence or distribution
attestation claim. Version selection, release branch/checklist, tagging and human
publication remain separate future authority.
