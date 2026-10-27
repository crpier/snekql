# Native UTC role follow-through (#477)

`004_clock.json` is actual public model-derived authoring after the committed
`role-interruption/mariadb/001_accounts.json`, `002_expand.json`, `003_roles.json` chain.
First writer:16e48f3 source plus the native-UTC checkpoint (no compiler changes).
Format2/epoch1; digest `5df892374b1b4bc324714d2a7f03f71d89016708be3eb7faae7d58a8348e0d7b`.
Never regenerate this reference for a changed compiler.

The visible `StampedAccount` declaration and complete authoring route are in
`tests/experimental/test_migration_native_utc.py`: two nullable native-DATETIME(6)/TEXT UTC
fields, named `stamp` checkpoint, typed UPDATE with column-aware CurrentTimestamp for both.
It uses an explicitly supplied codec-bearing historical declaration, not reconstruction from
coarse storage. Public compilation must still match the first-writer artifact literally.

Actual owned server defaults+05:30/-07:00 and NO_BACKSLASH_ESCAPES expose whether clock work
retains UTC meaning without clearing SQL-mode rendering evidence. Original001–003 files and
earlier receipts are not rewritten. Packages/models remain in process for this checkpoint;
model/author-free historical deployment and actual codec evolution were established earlier.
The new file is a fixed reference, not a claim of a deployed old004 receipt or repair of
previously written local timestamps.
