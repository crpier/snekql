# Recorded migrations: defined historical execution interpretation (#477)

Status: experimental checkpoint, not release/merge approval. This follows versioned
[prepared evidence](recorded-migrations-prepared-evidence-review.md) and the
[supported-scope proposal](recorded-migrations-supported-scope.md). No new operation,
adoption permission, SQL grammar, ledger layout or consumer guide.

## Defined interpretation rather than today's authoring compiler

Legacy package formats 2–8 now explicitly select **execution epoch one**. The capability
allow-list and epoch mapping are separate: adding a future capability cannot automatically
acquire a compiler interpretation. `Package.execution_epoch` exposes the defined interpretation
without adding fields, changing old package bodies or recalculating their identities.
An explicit future execution-epoch field is refused by this legacy reader, not coerced/defaulted
or silently converted. Only legacy epoch one is implemented; this is not an epoch-two registry.

`Package.load` replays the draft through `_migration_execution_v1.py`, not public `compile`.
The canonical operation grouping, emitted SQL, bindings, transaction flags, contractions,
capability selection and digest construction belong to that historical interpretation.
Current authoring delegates to that implementation today, but is a different caller: a future
authoring change cannot replace the historical reader merely by replacing the authoring verb.
`Package.check(current_route)` deliberately STILL calls current authoring compilation, so a
changed current emission is stale rather than mistaken for an unchanged historical artifact.

Target SQL projection/rebuild lowering belongs to `_migration_prepare_v1.py`. Preparation
explicitly selects the package epoch; original-plan application explicitly supplies its retained
epoch, requires agreement with the package, and rechecks through the supported historical
lowerer. There is no default current-lowerer choice at that dispatch seam. The saved original
plan is not reconstructed or rewritten; live target/catalog checks remain under coordination.

Current construction/admission and endpoint validators remain live. Moving the emitter/lowerer
does not freeze a catalog bug as truth, waive a stronger safety check, or retrospectively
upgrade receipts. Shared physical-state/parser/validation helpers can cause safe refusal;
this is not vendored historical Python/dependency execution. An incompatible interpretation
must retain supported historical semantics or refuse before mutation. Do not change epoch-one
emission/grouping to fit new authoring output, regenerate fixtures, or rewrite original plans.

## Enduring public-seam regression

`test_migration_execution_epoch.py` loads committed framework role packages, inserts real typed
initial rows, deploys the actual frozen historical typed backfill, independently adds an unowned
note/default, then prepares and saves the preserving deferred role contraction.

A copied runtime build has the PUBLIC authoring verb removed. Its real model/author-free client
loads the original versioned plan, retains exact bytes, loads the nested package, checks epoch
agreement, compares read-only epoch-one preparation and applies the ORIGINAL plan. Ordinary
current typed queries retain admin/user roles and note values. The consumer program passes ty;
normal/forced-lazy mode propagates to the child, which reports its actual copied module path.

This is dependency deletion at the authoring seam, not a mocked migration step, private helper
fault injection, declaration-state patch or fabricated receipt. The feature RED is the actual
historical loader calling the absent authoring compiler (falling through to Python's unrelated
builtin compile signature). An earlier raw ALTER result-shape refusal was a fixture/program
correction, not a newly found product runtime defect.

Additional regressions retain literal format-two/five bodies while exposing the SAME epoch one,
and refuse a future explicit epoch instead of selecting a default reader. All previous package
and Prepared-envelope references remain unchanged.

## Actual isolated candidate changes existing-operation emission

The separate experiment retained under `.snektest/477-execution-epoch/candidate/` uses actual
`d9a9f80` authoring implementation source, installed into a copied runtime with the new historical
reader. Its public compiler changes one policy: flush after each contraction operation instead
of grouping adjacent alterations. Historical helper bodies are unchanged. This produces a REAL
different execution for the SAME recorded role-contraction draft: two progress units/rebuilds
rather than one, not a renamed version constant, new capability or cosmetic SQL comment.

Observed through public interfaces only:

- Original package identity remains
  `99d5bc77258623790522bcf4d17f51315506d650209805333de9332c2023af27` (one unit).
- Candidate current authoring emits
  `ce57f74b2b29b7a1b3f682cde2152d5466acc203d6cb544516fcf0e9d6dce386` (two units).
- Original `Package.check(current_route)` refuses as stale.
- The epoch-one reader refuses the candidate grouping, even though the candidate's digest is
  internally calculated correctly. Adding an unsupported explicit epoch two also refuses.
- The SAME candidate runtime loads the original package and saved plan byte-identically,
  re-prepares through the defined lowerer, applies the original preserving contraction, retains
  earlier receipts, and leaves typed admin/user roles plus notes intact.

This candidate is NOT promoted as a supported writer or executed on the database. It intentionally
needs a different execution interpretation; the point is refusal rather than an invented automatic
adapter. The copied/archived source experiment is separate from CI: no vendored old-source tree,
Git archive/network dependency or compatibility framework is added to the test suite. Working
source is not mutated during native validation. Provenance/source hashes and actual output are
retained with the experiment; no private production step is replaced or made to fail.

## Bounds and remaining gates

This establishes one defined legacy execution interpretation and separates its emission/lowering
from current authoring, not a general compiler registry or promise to execute every future release.
The reader still canonically replays historical intent; it has NOT become digest-only validation.
Frozen canonical emission may be retained or explicitly refused when stronger safety cannot prove
it. Current helper/dependency/backend behavior and future wire/epoch admissions still require review.

Prepared persistence remains version one/epoch one, with caller-owned durable storage and the
database ledger's observation/reconciliation evidence required. No history conversion, portable
host-loss backup, generic downgrade fencing, application-readiness certificate or new replay/
reconciliation permission. Full deadline/session/config integration, finite maintained-version
qualification, WAL/native receipt-loss windows, historical authoring ergonomics and final
interface/ADR/release approval remain. Strict SQLite adoption and mapping/ownership separation
are unchanged. Prototype remains incomplete/not production- or merge-ready.

The subsequent [checked-out I/O deadline follow-through](recorded-migrations-io-deadline-review.md)
implements a bounded part of the remaining G3 work without changing this execution interpretation
or any historical package/Prepared bytes. Opening/acquisition and session/durability policy,
remaining outcome reporting, qualification and release decisions are not discharged by it.

## Completed local validation

- **876 normal +876 forced-lazy experimental**, **1,784 fast**, **19 focused normal +19
  forced-lazy**; all exited0 with zero failures/errors/fixture/session teardown failures.
  Native normal/lazy runs were sequential with separate external TMPDIRs and context-aware
  warnings. Production/test source hashes stayed unchanged throughout validation.
- Whole-tree ty/ruff/format645/diff checks pass; actual runtime consumer passes ty. All **68**
  prior package/Prepared JSON references remain byte-identical. Engineering links resolve.
- Actual copied candidate process retains original package/plan bytes and all earlier SQLite
  receipt columns/values, applies only original execution, and passes current typed reads.
  The incompatible candidate artifact is refused, never applied. Two completed isolated
  traces retain source provenance, actual new emission and observed outcomes; the second
  also compares full independent ledger observations, not merely public progress summaries.
- Full experimental runs retain the existing native interruption/restart/original-evidence
  regression; no new native acknowledgement-loss, WAL death, full-suite or maintained-version
  qualification claim follows. Owned test servers/runners are finished.

Environment: Linux/default asyncio, GIL-enabled CPython3.15.0, SQLite3.53.1, MariaDB13.0.2,
Pydantic2.14.0, aiosqlite0.22.1, aiomysql0.3.2/PyMySQL1.2.0. Not an exact-head CI-success claim;
CI pending/unregistered checks are neither awaited nor counted as local evidence.
