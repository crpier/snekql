# Recorded migrations: authoring-to-application review (#477)

Status: experimental engineering assessment, not a consumer guide or release decision.
The initial63dbc86 checkpoint returned to the product goal: author, review and deploy an
understandable schema-and-data transition. The staged-authoring improvement below addresses
its largest measured interface friction without expanding catalog parsing or operation authority.

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

## Initial interface assessment (63dbc86)

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

## Staged-authoring improvement

The SAME journey now uses the authoring module instead of manual reconstruction:

```python
route = (
    expansion.then(*CHANGES)
    .advance(
        [Account],
        removals=(m.DropColumn(table_name="accounts", column_name="is_admin"),),
    )
    .then(m.Checkpoint(name="final"))
)
```

`Draft.advance(models, *, removals=(), defaulted_additions=None)` generates and appends one
complete stage toward the supplied managed-model scope. It retains the real revision,
predecessor, original before-state, earlier operations and checkpoint-bound typed work.
No intermediate package/revision is exposed, serialized or needed as generation input;
model-derived generation shares one internal state-based implementation with `generate`.
The fixture imports its expansion draft from stage.py; no synthetic authoring revision,
manual state/operation/lineage copying, or undeployed expansion.json remains.

- The current route must compile and have no unresolved decisions. Refusal says to resolve
  the current stage before advancing, rather than laundering earlier decisions into a new target.
- New removal choices must be supplied in `removals` for THIS stage. It resolves them locally,
  so DROP INDEX/CHECK cannot move ahead of earlier creation/checkpoints/data work. Missing,
  unknown or unsupported choices raise; the original immutable draft remains usable. This is
  an atomic complete-stage method, not a new unresolved-stage serialization mechanism.
- Existing generate(...).resolve(...) remains available for initial authoring. In advance,
  use removals= rather than trying to resolve a refused new stage afterward.
- Source and composed route both pass existing compiler checks. Earlier checkpoint digests
  stay unchanged; stale typed work/late reuse after contraction still refuses. New method is
  not an exemption from construction, SQL-byte, endpoint, ownership or capability checks.
- Desired models still select migration scope explicitly. Handoff requires RelinquishTable;
  it emits no DROP and cannot authorize same-route recreation/adoption. No new backfill,
  default, destruction, constrained ADD or adoption policy is inferred. Existing explicit
  leave_null option is forwarded for defaulted additions, not automatically selected.
- Compiler validation internally compiles the prefix/composed route; this is offline work,
  not target observation. Repeated large stage chains have no new total-work/memory guarantee.

Both backends produce literal committed61036d9-writer package bytes through this smaller
interface. No new operation, format field/version, identity or ledger change. Existing
experimental historical-package and negative-authority guards remain intact.

This removes the measured stitching problem, not the entire authoring design queue.
Historical-source lifecycle, repeated declarations and author/build freshness integration
remain. Next product tasks stay workflow-first: ownership/preservation and genuine historical
evolution, then realistic interruption/coordination, finite scope/release reconciliation.
Do not resume attribute-by-attribute verifier expansion unless it blocks that scope.

## Evidence and limits

Local evidence: `.snektest/477-account-role-workflow/`, including persisted per-backend authoring,
packages, actual plans/outcomes, positive/negative static diagnostics and current application rows.
The initial incomplete authoring program omitted backfill; required-column validation refused NULL
rows, then adding the typed work made the journey pass. This is author-program TDD, NOT a newly
discovered library defect. Early status-order/type-diagnostic expectation corrections are excluded
from runtime-defect evidence. The initial checkpoint changed no production code; the new
advance interface is tested RED→GREEN at the existing authoring/compile seams.

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


New staged evidence: `.snektest/477-staged-authoring/`, including the SAME two-backend actual
consumer traces, committed-byte checks, real positive/negative static diagnostics and full
normal/forced-lazy suites. Missing-method RED and unresolved-prefix diagnostic RED are kept;
import sorting and input-test formatting corrections are not runtime defect evidence.


## Combined ownership follow-through

The [ownership lifecycle review](recorded-migrations-ownership-review.md) reuses the role
journey for query-only external mappings, strict adoption, reviewed unmanaged preservation,
non-destructive handoff and re-adoption. Clean roundtrip completes; preserved extras make
strict re-adoption refuse, and dependencies on the removed flag block preparation. This is
combined workflow evidence and a concrete partial-adoption scope decision, not new parser
or adoption permission. Genuine evolution/recovery and finite release scope remain next.


## Genuine application-codec evolution follow-through

The [evolution review](recorded-migrations-evolution-review.md) replaces a real serializer/
validator at the same module path before historical deployment on both backends. Frozen v1
bindings/receipts remain intact, while current v2 structural verification passes and logical
decode refuses until an explicit wire-representation migration. Opaque codec provenance is
not recoverable from unchanged schema hints/digests. This is application-codec evolution;
genuine framework compiler/package-format/ledger evolution still needs separate proof/policy.


## Actual framework capability and durable-layout follow-through

The [framework evolution review](recorded-migrations-framework-evolution-review.md) crosses
real archived prototype epochs: retain actual supported old receipts and role packages,
author/apply new format5 index work, demonstrate old compiler/reader refusals, and refuse an
actual incompatible ledger intact. Existing-operation emission ABI and finite support policy
remain open; interruption/coordination is the next workflow exercise, not more parser coverage.
