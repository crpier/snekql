# Recorded migrations: authoring-to-application review (#477)

Status: experimental engineering assessment, not a consumer guide or release decision.
This checkpoint returns to the product goal: author, review and deploy an understandable
schema-and-data transition. It adds no production interface or catalog-parser capability.

## The concrete journey

`tests/experimental/test_migration_authoring_journey.py` executes real consumer processes on
SQLite and an independently owned MariaDB server. Inspectable author-owned source templates
live in `tests/experimental/fixtures/account-role-workflow/`; the harness substitutes backend
and connection expressions only. No hand-built table/column states or declaration patches.

- Generate initial `accounts(id, is_admin)` from models, compile/serialize it.
- Generate nullable `role` expansion and a named `fill_roles` checkpoint. Write/import actual
  `contract_source` output as a Python module, rather than duplicating a historical model by hand.
- Author typed updates for True → admin and False → user. Generate the required-role contraction
  and explicitly authorize dropping is_admin. Join into ONE logical `002_roles` revision.
- Edit the route to initialize all roles then classify administrators. The previous artifact's
  `check(route)` fails; recompile a new identity, then prove an unchanged check succeeds. The
  edit changes data work/order, not checkpoint shape; checkpoint-shape freshness has separate tests.
- Check real generated/imported programs with ty. A deliberate `role.to(42)` assignment fails
  static checking; valid authoring, historical declarations, runtime and application pass.
- Physically delete authoring sources. Deployment gets only packages, its runner and a separate
  current application program. Migration process imports neither authoring nor application models.
- Prepare and inspect ordered ADD/backfill/contraction SQL and the required-role precondition;
  preparation does not record application. Apply explicitly, persist complete progress and return
  already_applied on repetition. Native caller exclusion is truthful on this private server.
- Separately verify the current application model (id/role, no is_admin), read `(1, admin)` and
  `(2, user)`, then insert/read `(3, user)` using typed ordinary application queries.

Normal and forced-lazy test modes also exercise isolated child programs in the corresponding
mode. Both backends take the same logical route, not a SQLite-only demonstration with assumed
native equivalence. No consumer application repository is modified.

## What this says about the interface

The core architecture CAN express the journey, including genuinely generated historical query
source, frozen model-free deployment, reviewed route freshness and ordinary typed application use.
It is not yet a comfortable authoring interface. The largest friction is visible in `review.py.in`:

1. **One logical revision needs manual draft stitching.** Expansion generation knows the
   intermediate target, not the eventual target. To generate the final contraction, the caller
   compiles an intermediate package solely as generation input, with an authoring-only revision
   name. The caller then copies generated operations and generated states into a new Draft with
   the real predecessor/revision. The intermediate package is never deployed. This exposes
   bookkeeping the module should own; a helper in the test would merely hide it.
2. **Three similar model declarations.** Initial, expanded and final shapes repeat stable fields.
   The intermediate shape is meaningful, but the author must currently express it separately
   before generating another query-only historical declaration. We should distinguish essential
   explicit schema decisions from avoidable declaration duplication, not infer a backfill policy.
3. **Historical-source lifecycle is manual.** Emit a source file, arrange imports, associate the
   checkpoint digest, type-check it and regenerate when its contract changes. The capability is
   real; its discoverability and workflow need a coherent story without a new CLI by default.
4. **Freshness must be deliberately integrated.** Loading a frozen package cannot know that
   unprovided authoring changed. The author/build step must call `Package.check(current_route)`.
   That distinction is correct; we must make the review/build happy path hard to omit, rather
   than couple deployment to today's application models.
5. **Status ordering needs an explicit presentation contract.** Backends returned progress in
   different orders here; the exercise compares revision membership, not an undocumented
   chronological order. This was an expectation correction, not a new execution defect.

## Next interface task, not another verifier slice

Remove authoring-only intermediate package/revision bookkeeping for composing one staged
transition. The module should retain the real revision/predecessor, current projected shape,
explicit removal decisions and checkpoint-bound data work while advancing toward model-derived
final intent. Callers should not reconstruct Draft state or silently discard unresolved decisions.
Choose a small interface at the existing authoring seam, then test the SAME journey through it;
do not introduce a second hidden test route or a parallel convenience framework.

This is a candidate task specification, NOT an approved new method name or an implemented
interface. Preserve explicit backfill/removal decisions, model/ownership independence, frozen
packages and stale-work rejection. Existing safety gates stay; prioritize new verifier work only
when required for this journey or the finite supported scope.

## Evidence and limits

Local evidence: `.snektest/477-account-role-workflow/`, including persisted per-backend authoring,
packages, actual plans/outcomes, positive/negative static diagnostics and current application rows.
The initial incomplete authoring program omitted backfill; required-column validation refused NULL
rows, then adding the typed work made the journey pass. This is author-program TDD, NOT a newly
discovered library defect. Early status-order/type-diagnostic expectation corrections are excluded
from runtime-defect evidence. No production code changed.

This does not establish genuine compiler/package/codec/ledger evolution, partial ownership,
interruption/recovery/competing-writer guarantees, arbitrary SQL equivalence, custom codecs,
whole-program resource bounds or blanket application readiness. Those tasks remain, alongside
finite backend/version/release scope and ADR reconciliation. Guides deferred; draft, incomplete,
not production- or merge-ready. No format/identity/history conversion or retrospective certification.


The reviewed initial/final format2 packages are committed under the workflow fixture's
`sqlite/` and `mariadb/` directories, emitted by the unchanged61036d9 writer. Tests compare
literal dumps with the author-generated route, then deploy the COMMITTED bytes, not a
silently regenerated replacement. Never regenerate these historical reference packages
merely to accommodate a compiler change. This fixes one writer epoch; genuine evolution
policy/testing remains separate. No history/receipt conversion or retrospective certification.
