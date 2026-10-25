# Fixed native AUTO_INCREMENT artifacts

Actual archived9b4b442 writer/reader/runtime emitted/loaded/prepared format2
`invalid-old.json`, digest
`0ca96e5471950bb1ff6d45f4f4e2609c7db07d9b8b996e0a57b3877e91c24d40`.
It records AUTO_INCREMENT but constructs a plain NOT NULL primary key. Native DDL commits,
then catalog proof refuses UNCERTAIN/AMBIGUOUS recovery: **not false completion**.
Current literal load/typed prepare refuse before effects/history.

Truthful `valid-old.json`, digest
`344bee433f8ea6ed72d4c0fe53c014d9aed67240538d7f733b7df253d9254f96`, retains literal dump/
digest/model-free generation/default7. Fresh owned native session produces distinct ids;
counter advancement does not invalidate a valid follow-up. Do not regenerate or convert
identities/ledger/receipts. No retrospective repair/revocation/history certification.

Bounded one ordinary native generator attribute; not exact counter/sequence/no-gap/non-reuse/
range/zero-input/sql_mode/offset/increment/future-session/codec/readiness certification.
SQLite rowid/AUTOINCREMENT policy remains separately checked. SQL trusted, not sandboxed.
