# Fixed identifier-claim artifacts

Exported by actual archived writer/reader
`3456c0541e0222f812329a528844d985c8efdf26`. Both are format 2.

- `valid.json`: generated SQLite `entries(id INTEGER PRIMARY KEY)`, digest
  `d8bf43b6df3a741ec93fe3cd3df74b2fc906b15f14f5700aa08414a8d2f9e6a5`.
- `mismatched-quoted-name.json`: the same construction SQL and managed name, but
  its independently recorded `quoted_name` is `"unowned"`. Digest
  `eafede39972be87990e8de612e12a9276ff9fdd146a36026df6e6e0b7ffe76bf`.
  The old compiler/reader accepted it. Current loading explicitly refuses it
  because subsequent ALTER operations could use that unrelated executable name.

Keep these bytes fixed. This is reader tightening with explicit refusal, not a
format conversion, receipt rewrite, compatibility promise for every historical
experimental artifact, or evidence that initial creation touched `unowned`.
No arbitrary construction SQL equivalence or publisher authentication is proved.
