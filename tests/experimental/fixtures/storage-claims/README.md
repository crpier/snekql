# Fixed construction-storage refusal artifact

Actual archived writer/reader/runtime
`5c4a6551b122dfb6489a08f4d36e36d5f61f7759` emitted/completed this format2 artifact,
digest `6f0c8c566e8034b3b4ccef4264594e0bd2308ad057943cc4dd3e8adbfa569041`. It claims INTEGER in the value column definition while construction
SQL uses TEXT. Old SQLite marked it complete, then stored 'not integer' as text.
Current compile/load/preparation explicitly refuse this mismatch before effects.

The valid companion is byte-identical to `../column-coverage/valid-old.json`, digest
`dd861098a813e3e1cb465536dc28b511d527b6fc82d1b53dd195e5d385e0a5c1`.
Keep bytes fixed: explicit refusal, not conversion, receipt/history rewriting or
retrospective certification. This compares physical definitions to construction;
coarse ColumnState.storage hints, Python codecs/defaults/other attributes and
arbitrary SQL equivalence remain separate contracts. No publisher authentication.
