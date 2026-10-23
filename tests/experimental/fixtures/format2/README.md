# Fixed format-2 writer fixtures

Exported on 2026-10-23 from an isolated `git archive` of writer revision
`8ae6024f1c9c2a843f96d84fff49f5e901ff880b`, not from the reader under test.
The writer's application models are not shipped/imported by the deployment test.

- `001.json`: SQLite `recorded(id INTEGER PRIMARY KEY, count INTEGER NOT NULL
  DEFAULT 7)`; digest
  `b3347011d819151583e88bb64e8cf7516a105d15ce3221fe653333d5432c1389`.
- `002.json`: add unconstrained nullable `note TEXT`, preserving the default and
  predecessor identity; digest
  `2fa94d43755cd8bae4d4cb1dfc1c0fd315b69c0c512a71f8ae307f7d041d9d12`.

Keep the bytes fixed. A changed compiler must either continue to accept and deploy
these identities, or make an explicit unsupported-format decision in its tests and
engineering contract. Do not regenerate the fixtures to hide a compatibility
break, rewrite an old digest, stamp old history, or infer codec compatibility.
These two fixtures do not certify every historical compiler or operation.
There is still no general old-format or ledger-upgrade support promise.
