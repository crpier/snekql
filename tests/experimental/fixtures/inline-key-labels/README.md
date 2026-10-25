# Fixed inline primary-key label artifacts

Actual archived `e1d3ef00ff232de6df173fbae5bdc20ef09be91c` writer/reader/runtime emitted,
loaded and completed `invalid-old.json` (format2), digest
`c8bce3f55f501b4be218d20dbb83ab6e56cacdda0edfaea963dec3630329da7f`.
ColumnState records `CONSTRAINT "recorded" PRIMARY KEY`; construction/sqlite_schema uses
`CONSTRAINT "other" PRIMARY KEY`. This is an identity contradiction, **not evidence of
lost uniqueness or changed write behavior**. Current load/typed prepare refuse before
schema/history. No native runtime false-completion claim.

Truthful `valid-old.json`, digest
`8233d25f2c8eb2bd3d75ca2abcbadc3736680148f781060b47e87e30bedc0d17`, retains literal dump/
digest, model-free default7 insertion and duplicate-key rejection. Do not regenerate/
convert identities, ledger or receipts. No retrospective repair/history certification.

Only bounded inline labels: not table-level key/index equivalence, namespace/implicit
native name proof, destructive authority, a schema/data equality solver or readiness.
SQL remains trusted executable input, not sandboxed.
