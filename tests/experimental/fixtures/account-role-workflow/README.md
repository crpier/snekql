# Author/review/deploy/application journey fixture (#477)

These are visible provisional author-owned programs, NOT a consumer guide, supported
file-layout convention, new CLI or test-only schema-state builder. The harness substitutes
only backend/config expressions. Every table/column state comes from model generation;
backfills import the actual generated historical source and are checked by ty.

1. `models.py.in`: initial, nullable expansion, required final declarations.
2. `stage.py.in`: initial frozen package, expansion authoring bridge and historical source.
3. `backfill.py.in`: explicit conditional typed updates for both flag values.
4. `review.py.in`: explicitly authorizes removal; joins generated expansion, typed updates,
   generated contraction into ONE logical `002_roles` revision. Intermediate package is
   never deployed. This manual stitching is current interface friction, deliberately visible.
5. `backfill_revised.py.in`: edit to initialize all roles then classify administrators.
   Existing artifact fails `Package.check(route)`; recompilation changes its identity;
   unchanged rerun is fresh. This changes data-work order, not the checkpoint schema.
6. Delete author directory; deployment directory contains only frozen packages, runtime
   and current application. `runtime.py.in` never imports authoring/current model modules;
   observes plan and required precondition, explicitly applies, records progress and reports
   already-applied on repeat. `app.py.in` separately verifies the current model, reads migrated
   rows and performs typed insertion/readback. Current model no longer declares `is_admin`.

Expected data: `(1, admin)`, `(2, user)`; typed new row `(3, user)`. Preparation does not
record application. No fixture declaration patches/model_copy/hand-built TableState/ColumnState,
private production helper assertions, raw migration SQL or new library interface. Raw seed
INSERT is test input data, not migration authoring. Generated historical wrong-role assignment
`role.to(42)` is statically rejected; valid sources pass. Child processes also explicitly inherit
forced-lazy mode when the parent runs forced-lazy. Private native server, no other schema writers.

Initial authoring RED omitted typed backfill: required-column check refused NULL rows. This
is a test-driven incomplete authored program, NOT a newly discovered product defect. Adding
backfill produces the full journey. Initial status-order expectation and type-diagnostic spelling
were corrected, NOT runtime defect evidence. Status order is not assumed across backends.

Known limits: default builtin primitive codecs only, no genuine compiler/package/codec/ledger
evolution, no interruption/concurrent runner/partial ownership proof in this fixture, no blanket
application readiness guarantee. SQL remains trusted. Manual composition, historical-source
file/import wiring and explicit freshness integration are reviewed in the engineering workflow
report. No production changes or additional parser work in this slice.


The reviewed initial/final format2 packages are committed under the workflow fixture's
`sqlite/` and `mariadb/` directories, emitted by the unchanged61036d9 writer. Tests compare
literal dumps with the author-generated route, then deploy the COMMITTED bytes, not a
silently regenerated replacement. Never regenerate these historical reference packages
merely to accommodate a compiler change. This fixes one writer epoch; genuine evolution
policy/testing remains separate. No history/receipt conversion or retrospective certification.
