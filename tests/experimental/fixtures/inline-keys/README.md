# Fixed inline-primary-key refusal artifact

Actual archived writer/reader/runtime
`6806ca6b169fed2610024c054c18a1a736de5a49` emitted, loaded and completed this
format2 artifact, digest
`cea471362c0fa3142565f02c5b2cb97811806ac9a3eb95a5f2e46d2b358c8847`.
The managed id definition records INTEGER PRIMARY KEY, but construction omits the
key. Old SQLite marked it complete, then accepted duplicate42 and NULL ids.
Current compilation/loading/typed preparation refuse before effects.

The valid companion is byte-identical to `../column-coverage/valid-old.json`, digest
`dd861098a813e3e1cb465536dc28b511d527b6fc82d1b53dd195e5d385e0a5c1`.
Its literal dump/digest and id42/default7 deployment remain valid. Do not rewrite
artifact identities or receipts. No format/ledger conversion or retrospective repair.

This binds bounded managed inline key policies, not full table-level key semantics,
key nullability, constraint names, all rowid modes, other conflict policies, index/FK
compatibility, codecs or application readiness. Extra SQL columns do not create
ColumnState claims. Construction remains trusted executable SQL, not a sandbox.
