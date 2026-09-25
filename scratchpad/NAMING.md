# Research naming decisions

Use these names in new research and examples until the user changes the convention.
Historical studies retain their original spelling. These decisions do not rename
production interfaces.

| Contract | Application class | Backend base |
|---|---|---|
| Construction contract, permitting designated generated values to be omitted | `User` | `sqlite.Model` |
| Queryable table and complete row contract | `UserRow` | `sqlite.Row` |

Apply the same convention to MariaDB and other examples, such as
`Account` / `AccountRow`.

The new namespace spelling replaces the previous prototype's `Input` base with
`Model`, and its previous `Model` marker with `Row`. The SQLite spelling and
annotation-only row refinements are now implemented in
`scratchpad/dual_basics/`. Earlier namespaces and MariaDB keep their original
spelling for now.

The first contract is not generally partial and need not contain omitted values.
A complete row constructor does not prove database existence or fetched provenance.
Neither storage contract is automatically a request or public response contract.
Password hashes belong in the storage contracts; plaintext registration passwords
and public response allowlists belong in separate operation contracts.

Row fields that become required use a narrowed annotation with no initializer,
for example `id: sqlite.Field[int]`. Do not show `required()` in the new primary
examples. The library preserves the inherited storage declaration internally.
