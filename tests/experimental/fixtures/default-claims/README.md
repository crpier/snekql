# Fixed construction-default refusal artifact

Actual archived writer/reader/runtime
`9cf8fd9a1fdbf8f1c95494f7d2870969e42ba0ca` emitted, loaded and completed this
format2 artifact, digest
`69cda581f7e5221ee6e75dfdfedca110244c537d2c19abf7c57128063ea9506d`.
The INTEGER column definition claims DEFAULT 7 while its construction uses DEFAULT 8.
Old SQLite marked it complete, then an omitted-value insert stored 8.
Current compile/load/typed preparation explicitly refuse the mismatch before effects.

The valid companion is byte-identical to `../column-coverage/valid-old.json`, digest
`dd861098a813e3e1cb465536dc28b511d527b6fc82d1b53dd195e5d385e0a5c1`.
Keep bytes fixed: explicit refusal, not conversion, receipt/history rewriting or
retrospective certification. This binds bounded default declarations, not Python
constructor defaults, codecs, arbitrary expression equivalence or write readiness.
Native nullable absence/NULL retain their existing effective-NULL contract; SQLite
keeps absence distinct from an explicit NULL declaration. No publisher authentication.
