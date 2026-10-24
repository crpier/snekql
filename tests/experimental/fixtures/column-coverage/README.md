# Fixed managed-column coverage artifacts

Both format2 artifacts were emitted and accepted by actual archived compiler/reader
`86f6ab10d7af0fd215763a04714cc80fea97df87`.

- `valid-old.json`: SQLite entries with id and default7 value, digest
  `dd861098a813e3e1cb465536dc28b511d527b6fc82d1b53dd195e5d385e0a5c1`.
- `invalid-old.json`: construction SQL creates id only, but the independent frozen
  ColumnState claims still list id and value. Digest
  `14e257ffbe3c205cf534128e48886a8e6af5f736519426f0213716a3788b0eec`.

An owned isolated SQLite deployment with the real old source marked the invalid
package complete while PRAGMA table_info contained only id. Current compile/load
and preparation explicitly refuse the missing managed declaration before effects.
The valid companion must retain its bytes/identity. Keep both artifacts fixed;
this is explicit refusal, not conversion, re-signing or receipt/history rewriting.
No general declaration equivalence, ownership inference from extra SQL columns,
legacy experimental-format support or publisher authentication is promised.
