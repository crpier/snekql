# Fixed key-implied nullability artifacts

Actual archived `9eb468ed4b06f960c09b5bdf69ac522d30e9fa43` writer/reader/runtime:

- `invalid-old.json`, format2 digest
  `7e1212b672040c56705052e4653c4cd4f544917c179b8f544f28c1094a1a9d3d`:
  SQLite non-STRICT TEXT PRIMARY KEY, required metadata, no explicit NOT NULL.
  Old runtime completed, then stored two NULL ids. Current load/typed preparation refuse.
- `valid-old.json`, format2 digest
  `5d11c3e2c381e4346ab451b27c775725d4c542ce1aaf43ab8ce4afe4782d8449`:
  truthful nullable metadata/annotation. Literal dump/digest retained; current model-free
  deployment permits the same two NULL values without changing metadata identities.
- `native-invalid-old.json`, format2 digest
  `38a4b1e3d790f16fbebcedb58c08fb9fe974a86e19414fdbf505f5800e576fec`:
  native BIGINT table-level primary key, nullable metadata. Old runtime prepared and
  executed DDL, then refused on native nullability, leaving uncertain effects and
  ambiguous recovery. **Not native false completion.** Current load/typed preparation
  refuse before effects; a separately authored truthful required package deploys.

No format/ledger/receipt conversion, retrospective revocation or automatic repair.
Key-implied/declaration nullability is not a solver for CHECK/FK/trigger/data/codec or
application readiness, all key attributes, constraint identity or namespace equivalence.
SQL is trusted executable input. Do not regenerate old artifact identities.
