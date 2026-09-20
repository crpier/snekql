# MariaDB release support

Python 3.14+ and aiomysql remain required. This matrix does not add MySQL support
or change the explicit Database/Transaction API.

## Release policy

The maintained Community LTS targets are **10.11, 11.4, 11.8 and 12.3**. Install
current security patches within a target series. The runtime admission floor is
10.11; accepting a version number does not certify every intervening release,
old patch, operating system or downstream distribution.

| Series | Community maintenance ends | Validation role |
| --- | --- | --- |
| 10.11 | 2028-02-16 | Oldest maintained LTS target |
| 11.4 | 2029-05-29 | Established LTS target |
| 11.8 | 2028-06-04 | LTS target |
| 12.3 | 2029-06-12 | Current LTS target |
| 12.2 | Not a maintained LTS target | Retained catalog-crash and compatibility regression target |
| 12 rolling repository | Depends on the resolved series | Forward regression coverage; effective version recorded by CI |

Maintenance dates come from the [MariaDB Foundation maintenance policy](https://mariadb.org/about/),
checked 2026-09-20. Upstream may revise dates. Enterprise and extended-support
contracts are separate; this project does not provide them. MariaDB 10.6 ended
Community maintenance on 2026-07-06 and is outside the admission floor.

## Capability audit

The selected families share the SQL/type contract below. No version-dependent
fallback disables validation, weakens transactions or substitutes storage types.
The older-release change is conditional on the entire native integration suite,
not just a successful connection or a changed version constant.

| Area | Required behavior and retained limits | Coverage |
| --- | --- | --- |
| Reads | Parameterized queries, explicit row scope, joins, subqueries, aggregates, LIMIT/OFFSET | Query compilation and runtime suites |
| Reporting recipes | Validated raw SQL for CTEs, recursive CTEs, windows and set operations; these are not query-builder methods | Executable reporting recipes |
| Writes | INSERT RETURNING, multi-row writes, ON DUPLICATE KEY UPDATE with VALUES references | Insert/conflict/bulk runtime suites |
| Locking | FOR UPDATE, NOWAIT, SKIP LOCKED; no query replay after uncertain I/O | Row-locking, deadline and commit-outcome suites |
| Plans | EXPLAIN and MariaDB ANALYZE; no INSERT plan inspection | Plan compilation/runtime suites |
| Native types | BIGINT, BOOLEAN, DOUBLE, DATETIME(3), DECIMAL, JSON, UUID and bounded text/blob storage | Codec, round-trip and schema suites |
| Declarations | Bounded utf8mb4 collations, prefix indexes, candidate keys, composite foreign keys, checks and defaults | Declaration, scaffold and drift suites |
| Migrations | Advisory serialization, byte-exact history names/checksums, enforced history constraints, partial-DDL failure handling | Migration/baseline/recovery suites |
| Connections | Strict SQL mode, UTC, checks/FKs/uniqueness enabled, InnoDB pages at least 8192 bytes | Session-policy and acquisition suites |
| Transport/lifecycle | Verified TLS, recycling, disconnect/restart handling, cancellation, streaming cleanup and process ownership | Native TLS, failure and test-server suites |

Native UUID storage requires MariaDB 10.7 or later. INSERT RETURNING and
SKIP LOCKED also precede the 10.11 target. There is no UUID-as-text substitution
or silently unlocked query on older servers. The public Index declaration does
not promise descending-index members; SQL ORDER BY DESC is a different feature.

The catalog reader recognizes MariaDB JSON's LONGTEXT representation and reads
foreign-key members/actions separately. This avoids the MariaDB 12.2.2 virtual
catalog-join crash while preserving the same structural checks on older targets.
Missing foreign-key action metadata fails verification. Unmodeled expressions
retain their existing unchecked status rather than becoming invented matches.
Verification remains partial; it does not certify arbitrary hand-authored DDL.

### Unsupported-feature diagnostics

- `Database.initialize` raises `DatabaseRuntimeError` for a pre-10.11 server,
  an unidentified server or MySQL. The message states the required floor and
  reported version. Failed session-policy checks also prevent admission.
- MariaDB query compilation rejects UPDATE RETURNING and DELETE RETURNING with
  `QueryCompilationError`. These are library restrictions. MariaDB's own DELETE
  RETURNING syntax does not make that operation part of this query API.
- MariaDB partial-index declarations remain rejected. Unsupported declarations
  fail instead of dropping their predicates or changing uniqueness semantics.
- Plan compilation rejects INSERT inspection. Executing ANALYZE has the existing
  explicit execution consequences; changing server version does not make it a
  non-executing estimate.
- Raw SQL is caller-owned SQL. Version admission does not certify arbitrary
  statements or introduce MySQL compatibility.

## Validation and reproduction

CI installs native server/client binaries for each listed fixed series on
Ubuntu 24.04, asserts the selected series, then runs `uv run snektest tests`.
The existing 12 rolling job also runs the full suite. Jobs record actual server,
Python, SQLite and OS versions. A shared Docker database service is insufficient:
restart, TLS, password bootstrap and process-cleanup tests start their own
servers using the selected native binaries.

For local reproduction, use an isolated checkout/environment per release and
install that release's native tools. Follow the private temporary-directory and
`PYTHON_CONTEXT_AWARE_WARNINGS=1` setup in the
[failure matrix](failure-matrix.md#reproducing-deterministic-checks). Install timezone data including
legacy aliases. On Ubuntu 24.04 these aliases come from `tzdata-legacy`; older
Ubuntu packages may include them in `tzdata` itself.

Keep complete logs and the exact package version or container image digest.
Run suites sequentially within each checkout and fixture directory. Isolated
containers can run concurrently, but share neither the checkout's writable
fixture directories nor the test server's data files.

These tests validate the library against fresh isolated servers. They do not
validate in-place database upgrades, data-directory downgrade, replica topology,
plugins, arbitrary server tuning or another operating system. Review MariaDB's
upgrade documentation and your own production workload separately.
