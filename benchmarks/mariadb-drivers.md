# Direct MariaDB driver comparison

Tracking: [#478](https://github.com/crpier/snekql/issues/478).

This compares **aiomysql and asyncmy**, not snekql versus another library. It
reuses the comparative harness's owned server, session policy checks, environment
metadata and heartbeat, but performs direct driver operations without Pydantic or
query builders. It does not change the runtime dependency or certify a migration.

[Dated findings and raw results](mariadb-driver-findings.md) summarize the first
local comparison.

## Run

From a source checkout with the project's Python 3.15 and MariaDB binaries:

```sh
root=$(mktemp -d "$HOME/.cache/snekql-drivers-XXXXXXXX")
mkdir "$root/tmp"
TMPDIR="$root/tmp" uv run --locked --with asyncmy==0.2.16 python \
  -m benchmarks.mariadb_drivers --workload point-read --operations 5000 \
  --rows 10000 --trials 6 --warmup 100 --workers 1 \
  >"$root/point-read.json" 2>"$root/stderr.log"
```

Check the exit code before consuming JSON. Missing dependencies/server tools,
policy mismatches, driver errors or incorrect results abort the command. Output
is a single JSON document only after every trial succeeds.

`uv --with` installs asyncmy into an isolated overlay; `pyproject.toml`, `uv.lock`
and installed users' extras remain unchanged. A compiler may be needed if no
wheel matches the interpreter. CLI integration tests also use this pinned overlay,
so their first run may need package-index access and compilation. Other dependencies
come from the project lockfile. The uv version itself is not pinned by this command.

| Option | Default | Bounds |
| --- | --- | --- |
| `--workload` | `point-read` | `point-read`, `buffered`, `stream`, `write`, `bulk` |
| `--operations` | 1000 | 1–100000, total per driver/trial |
| `--rows` | 1000 | 1–1000000, seeded read table |
| `--trials` | 4 | 1–30, per driver; prefer even counts |
| `--warmup` | 100 | 0–10000, **per connection**, before every trial |
| `--workers` | 1 | 1–128, one dedicated connection per worker |
| `--batch-size` | 256 | 1–10000, streaming fetch or multi-row INSERT size |

For scans, one operation consumes the **entire dataset**; reduce operations and
warmup accordingly. Run `--workers 8` separately for concurrent server requests.
Each worker gets a disjoint strided subset of operation indices. There is no pool,
checkout measurement or connection sharing. Worker counts do not measure fairness.

## Comparable work

Both drivers use loopback TCP, utf8mb4, explicit BEGIN/acknowledged COMMIT, and the
same verified strict-mode, UTC, isolation and integrity settings described in
[the runtime comparison](comparison.md). Every worker's effective session policy
is checked and recorded before warmup. Seed data is shared between drivers on one
private server. No external database or credentials are used.

- **point-read:** parameterized primary-key lookup, wrapping through seeded IDs.
- **buffered:** ordered scan using a normal cursor and `fetchall()`.
- **stream:** ordered scan using `SSCursor.fetchmany(batch_size)`; verify every
  batch and yield to the event loop between batches. No full scan accumulation.
- **write:** one parameterized INSERT, commit, then a separate transaction reads
  back that row and commits.
- **bulk:** the same write/readback operation using a parameterized multi-row
  INSERT, not `executemany()`. `batch-size` rows are inserted per operation.

Every row's identity, order, email and payload is checked, as is cardinality.
These checks are timed and identical across drivers. Inputs are integer IDs,
ASCII email strings and a 32-byte ASCII payload; this is not a comprehensive
codec/type benchmark. Writes use disjoint identity ranges across workers. The
write table is cleared before warmup and again before measurement. After each
write trial, an **independent physical connection** audits the whole committed
result outside timing. Lost writes cannot produce a successful report.

Trial order alternates aiomysql/asyncmy then asyncmy/aiomysql. Setup, opening and
configuring connections, warmup, independent commit audit and teardown are outside
timing. Query construction, parameter encoding, row decoding/checking, transaction
commands, cursor handling and each write's readback remain inside timing.

## Report and interpretation

JSON schema version 1 records command configuration, each trial, actual package
and server versions, server durability variables, Python/OS/CPU details, Git
revision/dirty state and server data-directory location. Latency percentiles use
the existing harness's interpolation. Throughput is **verified operations/sec**,
not queries/sec or rows/sec. Writes include two transactions per operation.

The common 5 ms heartbeat reports event-loop wakeup lateness during work, including
OS scheduler delay. A null `loop_stall` means no completed sample, not zero stall.
Latency starts at the worker's operation entry: this is closed-loop load, without
an independent arrival process or external request-queue measurement.

Limitations:

- No pooling, TLS, remote-network latency, failure recovery or cancellation audit.
- No prepared statements, native bulk protocol, mixed workloads or type matrix.
- No memory/peak-RSS measurement; a streaming batch bound is not a total-memory bound.
- Server and client share the host. OS/server caches and physical table allocation
  are not reset between trials. Alternating order reduces but cannot remove drift.
- Storage matters for writes. `/tmp` may be tmpfs; use an explicit disk-backed
  `TMPDIR`, record the filesystem, and inspect the actual server durability settings.
- Short runs, especially small scans, cannot support strong tail-latency claims.
- A faster raw driver does not establish equivalent snekql lifecycle guarantees.

Tests:

```sh
uv run snektest tests/test_mariadb_driver_benchmark.py
```

They exercise real-driver CLI output, rotating order, values/counts, concurrent
connections, bounded batches, invalid arguments, and driver-boundary faults
(wrong data and acknowledged-but-lost writes). A public aiomysql streaming cursor
fault guard forbids `fetchall()`; Cython asyncmy methods are not monkeypatched.
No machine-dependent performance threshold is a test assertion.
