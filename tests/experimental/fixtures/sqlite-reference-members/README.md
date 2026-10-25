# Fixed explicit referenced-member contract

Actual archived `7b20272` writer/reader/runtime emitted, loaded and completed this real
format2 contract with matching child FK DDL and an ordinary external parent, but the
referenced column was absent and child writes failed with `foreign_keys=1`. This is a
referenced-member readiness gap, NOT missing/mismatched-FK construction or orphan acceptance.

Digest: `7a1f065a02941b376b04514bb4dc335965a3baf6a5f2193732348885df2e6704`

The SAME body/digest/load works on old/current runtimes with an observed ordinary parent
that declares `id`, valid/NULL child writes and orphan rejection. Missing explicit members
now refuse pending prepare pre-effects; the endpoint recheck protects completion. No parent
adoption, format/digest/ledger/receipt conversion, repair/revocation/retrospective certification.
Old complete/already-applied receipts remain prior execution evidence, not new certificates.

Explicit single/composite full-column names only; SQLite ASCII folding, quoted names, actual
rowid-named columns retained. No inference from rowid aliases, labels, literals, Unicode fold
or query addressability. Implicit table-FK parent-key resolution remains a separate gate;
this check retains base-table observation only for implicit member lists. Not key/index/arity/
type/collation/data/session/codec/query-readiness/full FK compatibility or resource/recovery
proof. Inline implicit/composite language remains adapter-only; no new operation permission.
Trusted executable SQL remains unsandboxed. Never regenerate/convert this artifact.
