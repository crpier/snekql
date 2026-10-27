# Fixed NOT NULL policy artifacts

Actual archived `86464d677cfb58ca5f4b11b6188014f9fb8be3b4` writer/reader/runtime emitted,
loaded and completed `invalid-old.json` (format2), digest
`3c730b701101b3a2c04cdad4994f880c3b289740749d68e168a4624c90805ee2`.
It records NOT NULL ON CONFLICT IGNORE but constructs REPLACE with default7.
Old SQLite marked complete, then a NULL write inserted id42/value7 rather than skipping.
Current load/typed preparation refuse before effects/history.

`valid-old.json`, digest
`d57c16bdec96277408d7c4db89a91e4cc618c73ebdd9e8dd6fd9919eb4047049`, records and constructs
IGNORE. Its literal dump/digest and model-free NULL-write skipping remain unchanged.
Do not regenerate identities or convert ledger/receipts. No retrospective repair.

This binds explicit NOT NULL presence/policy/label, not key-implied requiredness, a
full value-domain solver, other constraint policies, native session coercion, CHECK
identity/removal authority, live catalog completeness, codecs or readiness. SQL remains
trusted executable input, not sandboxed. No native false-completion claim for this slice.
