# Author/review/deploy/application journey fixture (#477)

Visible provisional author-owned programs, NOT a consumer guide, supported file-layout
convention, new CLI or test-only schema-state builder. The harness substitutes only backend/
config expressions. Every table/column state is model-generated; typed backfills import the
actual generated historical source and are checked by ty.

1. `models.py.in`: initial, nullable expansion, required final declarations.
2. `stage.py.in`: defines the initial package and expansion draft once; when executed, writes
   initial frozen package and historical source. Imported by review without file writes.
3. `backfill.py.in`: explicit conditional typed updates for both flag values.
4. `review.py.in`: `expansion.then(*CHANGES).advance([Account], removals=(DropColumn(...),))`
   appends generated contraction in the SAME logical002_roles revision. No undeployed
   intermediate package, synthetic revision, hand-joined operations/states or lineage copying.
5. `backfill_revised.py.in`: edit to initialize all roles then classify administrators.
   Existing artifact fails `Package.check(route)`; recompilation changes its identity;
   unchanged rerun is fresh. This changes data-work order, not checkpoint schema.
6. Delete author directory. Deployment directory contains only committed frozen packages,
   runtime and current application. `runtime.py.in` never imports authoring/current model
   modules; prepare is inspected without recording application, then apply/repeat reports
   complete/already_applied. `app.py.in` separately verifies the current model and performs
   typed reads/insertion/readback. The current model no longer declares is_admin.

Expected data: `(1, admin)`, `(2, user)`; typed new row `(3, user)`. No fixture declaration
patches/model_copy/hand-built TableState/ColumnState, private production helper assertions
or raw migration SQL. Raw seed INSERT is fixture input only. Actual historical `role.to(42)`
is statically rejected; valid sources pass. Forced-lazy parent explicitly propagates mode
to child consumers. Private native server with truthful schema-writer exclusion.

Initial63dbc86 workflow used manual stitching via an undeployed intermediate package. Its
initial incomplete authoring RED omitted backfill; required-column check refused NULLs, not
a newly discovered library defect. New staged interface RED first lacked Draft.advance; a
second RED sharpened unresolved-prefix guidance. Stage-local index/CHECK removals, explicit
handoff/no same-route recreation, defaulted-addition choice and stale-contract checks stay
public authoring/compilation tests. No new parser or operation authority in this improvement.

Reviewed initial/final format2 packages in `sqlite/` and `mariadb/` were emitted by unchanged
61036d9 writer. Tests compare literal dumps from the NEW authoring interface, then deploy
COMMITTED bytes. Never regenerate these historical references to accommodate a compiler
change. One fixed writer epoch, NOT genuine compiler/package/codec/ledger-evolution proof.
No history/receipt conversion or retrospective certification.

Default builtin primitives only; interruption/concurrent runner/partial ownership/resource/
release-scope guarantees remain separate. SQL trusted, readiness separate, draft/not ready.
Historical-source lifecycle, repeated model declarations and freshness integration still
need interface review. See `docs/proposals/recorded-migrations-workflow-review.md`.
