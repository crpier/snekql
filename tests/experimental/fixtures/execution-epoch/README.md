# Historical execution independent of public authoring (#477)

`runtime.py.in` is a real model/author-free operator. It loads a retained original Prepared
file, preserves its bytes, checks the package/plan epoch, compares read-only historical
preparation and applies the original deferred plan. The test seeds ordinary typed data using
committed framework role packages and an independent unmanaged note/default. No hand-built
schema-state declarations or ledger rows.

The copied runtime deliberately omits public `compile` to test dependency deletion: loading
historical execution must not call a deployment build's authoring verb. Canonical epoch-one
interpretation is retained. This does not prove a runtime can omit all interpretation/validation
code, or that Package.check can work without the current authoring compiler.

The separate actual altered-emission experiment uses archived d9a9f80 compiler source in an
isolated copy and changes public compilation to produce separate progress units per alteration.
Historical helper implementations are unchanged; no private execution step is fault-injected.
That source is not vendored here or needed by CI. Its actual bodies/digests/refusals/original-plan
application are retained under `.snektest/477-execution-epoch/candidate/`.

Existing legacy formats2–8 select epoch one without changing package bytes. Explicit future
epochs stop until a supported reader exists. Live safety gates still apply; no historical
conversion, receipt rewriting, automatic replay/repair, general future compiler/dependency ABI,
downgrade fencing or application-readiness guarantee. Engineering fixture, not consumer guide.
