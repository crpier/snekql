# Fixed collation construction artifacts

Actual archived `8e7c243` writer/reader/runtime emitted/loaded/completed format2
`invalid-old.json`, digest
`7255b12d6c51cbc8b40c0993591c246bbf2075a04c9af8b7d58f9ba58a5ed718`:
NOCASE metadata/BINARY construction, then accepted default 'Case' plus 'case' under UNIQUE.
Current literal load/typed prepare refuse before effects/history.

Truthful NOCASE `valid-old.json`, digest
`08791084aef62cf8dd4b015ccad4b3dce732c495278a74782582ef2c76a66c3f`, retains literal dump/
digest/model-free default 'Case' and case-only duplicate rejection.

Actual archived native `native-invalid-old.json`, digest
`a8da038c6857a0cd509e30cc7dd4a04483cb29037ade6d9bd85e417d553f1356`, prepared, committed
DDL with general_ci rather than recorded bin, then refused UNCERTAIN/AMBIGUOUS recovery.
**Not native false completion**; current refusal moves before DDL/history.

No identity/ledger/receipt conversion, retrospective repair/history certification. Bounded
SQLite BINARY/NOCASE/RTRIM and native existing type-prefix utf8mb4/JSON-bin name contract,
not arbitrary equivalence/locale/Unicode/version/registry/override/data/session/readiness
proof. SQL remains trusted, not sandboxed. Do not regenerate fixed identities.
