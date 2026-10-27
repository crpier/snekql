# First versioned original-plan evidence (#477)

Engineering fixtures, not a consumer guide or release compatibility promise.

`apply.py.in` is a model/author-free replacement operator: load the original retained plan,
then apply it without preparing a replacement. The test renders/checks this actual program
and propagates forced-lazy mode to the child. Ordinary application models and typed reads
remain in `test_migration_prepared_evidence.py`, independent of migration ownership.

`sqlite-role-contraction.json` is literal output of the first `Prepared.dump` implementation
on top of 827172c, exported from an ACTUAL SQLite target before application, not a fabricated
plan/receipt. The producer loads committed framework-evolution 001/002/003 packages, inserts
real typed initial rows, deploys the existing typed role backfill, adds an independent unowned
note/default, then prepares the deferred contraction with preservation explicitly enabled.
A replacement process applies the retained plan and keeps both role rows and note values.

Wire version 1; execution epoch 1; envelope digest:
`a7fb2bb11333d5772ee8ca19c272d7dc1452a467c4e61e9bb6ff95bc172be828`.
The nested package is unchanged actual format 2 framework 003:
`99d5bc77258623790522bcf4d17f51315506d650209805333de9332c2023af27`.
The target ID binds the original observed target/configuration; this fixture is NOT a portable
plan to apply against a fresh database. Reader regression loads/dumps unchanged bytes only.
Never regenerate it to accommodate changed compiler/preparation behavior.

Producer/evidence: `.snektest/477-prepared-evidence/sqlite-deferred/` retains the actual database,
original file, operator, rendered-program ty result and observed rows. The producer script is
retained externally under `/home/crpier/.cache/snekql-477-prepared-evidence/trace.py`. The native
trace in the same evidence root exercises original-plan load after client death/server restart
and real competing resume. The role-interruption fixture's operator now uses dump/load instead
of treating raw public Pydantic JSON as a persistence interface.

The versioned envelope is bounded and integrity checked, not authenticated or encrypted.
Callers own permissions, atomic publication, durable storage and backups before native apply;
writing text in this test is not a power-loss/host-loss durability proof. Raw unversioned plans
have no automatic conversion; preserve their evidence and stop for separately designed recovery.
Package.load still recompiles and ordinary apply still rechecks current target lowering. Epoch
metadata on a prepared plan does not solve the separate historical package/compiler contract.
