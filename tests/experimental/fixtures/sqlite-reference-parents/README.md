# Fixed SQLite external-parent contract

Actual archivedb106fd1 writer/reader/runtime emitted/loaded/completed this real format2
with matching child FK DDL but a missing external parent; child writes failed. This is a
referenced-parent readiness gap, NOT a missing/mismatched-FK construction contradiction.

Digest: d6a09e1a4489ca946611a82f4747a01a578c388c140e91ba75457ccc96b6e53e

Same artifact must retain literal dump/digest/load: an observed ordinary external parent
makes it deployable without parent adoption. Missing/view/virtual parent now refuses pending
preparation read-only. New endpoint recheck protects completion; preparation-only copied
bypass rolls back child+history, while parent-validator-only omission reproduces old completed
unusable-parent context. No artifact/ledger/receipt conversion, retrospective revocation/
certification/repair, full parent-key/index/type/collation/data/future-session/readiness proof
or recovery shortcut. No new FK operations. SQL trusted/unsandboxed.
