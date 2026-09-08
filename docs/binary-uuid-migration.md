# Binary UUID storage compatibility

`Col[uuid.UUID] = Blob()` stores the UUID's 16 bytes in UUID byte order, matching
`UUID.bytes`. Equality and `IN` parameters use the same representation. This
applies to inserts and updates on SQLite and MariaDB. Pydantic still validates
logical UUID types, including version-constrained annotations. A custom serializer
that already produces bytes keeps control of its representation.

Earlier encoding left a UUID object in driver parameters. SQLite rejected these
writes; MariaDB could store the UUID's 36-byte hyphenated ASCII text instead.
Existing MariaDB ASCII UUID bytes remain readable through validated UUID fetches.
They **do not match** corrected binary UUID equality or membership parameters.
Reads do not rewrite them, and this fix does not run a data migration.

Before deploying against existing UUID Blob data:

1. Stop old writers and back up the affected data. Inventory raw stored values,
   including related UUID keys and foreign-key columns.
2. Validate candidate ASCII values as UUIDs. Do not convert arbitrary Blob data
   based on length alone. Resolve duplicate logical UUIDs represented by different
   byte strings before conversion, especially with unique keys.
3. Rewrite audited values to `UUID.bytes`, coordinating related keys and
   constraints. Find legacy rows by an independent stable key or their existing
   raw bytes, not by the corrected UUID predicate.
4. Verify raw 16-byte storage, logical reads, equality/IN lookups and referential
   integrity before resuming writers. Prevent older application versions from
   restoring text-encoded values.

For a table with an independent integer `id`, a controlled application rewrite
can fetch the UUID by `id` and update that same row by `id`:

```python
async with database.transaction() as tx:
    account_id = await tx.fetch_one(
        select(Account.account_id).where(Account.id.eq(row_id))
    )
    await tx.execute(
        update(Account)
        .set(Account.account_id.to(account_id))
        .where(Account.id.eq(row_id))
    )
```

This example handles one already audited row. It is not a general foreign-key or
unique-key migration plan. Text UUID columns and MariaDB native `Uuid()` storage
are unchanged and should not be converted by this procedure. Custom serializers
may deliberately use another byte order or representation; audit those separately.
