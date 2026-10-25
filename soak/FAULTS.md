# Real fault drills (source checkout)

Tracking: #544. These bounded operational drills complement the long-lived
[service soak](README.md). They use public transaction/stream/outcome interfaces
and actual owned OS faults, not patched driver replies. They are not a benchmark,
retry policy, or certification of every production topology.

## Run

Use Linux, CPython 3.15+, the locked development environment and native MariaDB
server/client/install tools. SQLite additionally needs util-linux `unshare`,
`mount` and `umount`, with private unprivileged user/mount namespaces enabled.
No sudo or host-level changes are performed. Lack of namespace/mount capability
makes the **CLI fail**, not skip or report success.

```sh
uv sync --locked --all-extras
root=$(mktemp -d "$HOME/.cache/snekql-fault-drills-XXXXXXXX")
mkdir "$root/tmp"
for scenario in stream-cut commit-blackhole restart-load sqlite-full; do
  status=0
  TMPDIR="$root/tmp" PYTHON_CONTEXT_AWARE_WARNINGS=1 \
    uv run python -m soak.faults --scenario "$scenario" \
    > "$root/$scenario.jsonl" 2> "$root/$scenario.stderr" || status=$?
  printf '%s\n' "$status" > "$root/$scenario.status"
  [ "$status" -eq 0 ] || break
done
printf 'Evidence: %s\n' "$root"
```

Run sequentially and preserve stdout, stderr and exit status, including failures.
Use ordinary foreground signal handling; background launchers must reset inherited
ignored SIGINT/SIGQUIT before exec. Native helper startup/cleanup has its own
budgets; the per-operation deadlines below are not total process-spawn deadlines.

All endpoints, data directories and mounts are freshly owned by the command.
There are no host, port, credentials, SQL, directory or fault-target CLI options:
it cannot be pointed at an existing application database. The proxy listens on
loopback and connects only to the server created by that run. It never changes
machine networking. Normal helper shutdown owns/reaps the native server; failure
logs may retain temporary native-server artifacts. Only delete this run's root
once its processes have exited. Do not clean other runs' databases.

## Fault handshakes and checks

| Scenario | Real fault and proof of placement | Required public recovery evidence |
| --- | --- | --- |
| `stream-cut` | A plaintext loopback TCP proxy relays a 4,096-row / 4,096-byte-payload stream. After the consumer receives IDs 1–4, it aborts current sockets. Forwarded bytes must be less than the complete payload, so the fault cannot be injected after full delivery. | The delivered prefix has consecutive IDs and expected payloads. A later fetch fails with `connection_loss`, not clean completion; the Transaction is unusable. Exactly one unsafe lease is discarded; the size-one pool drains and a fresh Transaction returns 42. Buffered rows may arrive after the first batch: no assertion that the immediately next fetch fails. |
| `commit-blackhole` | After an InnoDB insert, the proxy forwards a real COM_QUERY COMMIT and withholds server-to-client packets on that connection while keeping sockets open. It must observe a server OK and exactly one forwarded COMMIT before recovery. No driver methods are patched. | A one-second Transaction deadline raises `DatabaseOperationTimeoutError`; `commit_outcome` remains `unknown`. The server/proxy's OK is **not** a driver acknowledgement. A fresh Transaction reconciles operation key 544 to the single expected value 7. No write replay occurs; another fresh read succeeds. |
| `restart-load` | Four native `SLEEP(30)` queries must be visible in the owned server's process list, while four more callers are provably queued through public pool stats. The helper stops its server, interrupted requests settle, then a new server starts on the same port/data directory. | All four active requests report `connection_loss`; all queued requests finish with errors. Known committed IDs 1–4 survive. The **same Database** reads them and commits a new ID 5 after restart. No interrupted query is replayed. |
| `sqlite-full` | A child enters distinct user and private mount namespaces, mounts only a fresh 4-MiB tmpfs, and fills it until an OS write returns ENOSPC and available blocks are zero. An actual SQLite WAL/FULL write then fails with native SQLITE_FULL (13). No `max_page_count`, mocked exception, global mount or normal database is used. | Free the owned filler, wait for detached physical cleanup via public pool stats, and reconcile only preexisting ID 1. New ID 3 commits and reads back; failed ID 2 never appears. Report actual Commit Outcome without assuming a failure proves rollback; reconcile before any retry. Close the Database before unmounting. |

The restart's queued errors may be checkout/connection failures or acquisition
timeouts. We retain their public exception types rather than label them all
active connection loss. The restart is a cooperative real process shutdown/start,
not SIGKILL, crash/power-loss, upgrade or replicated-failover certification.
Its in-flight requests are read-only; writes are acknowledged before and after
the outage. The commit blackhole separately covers an in-flight write outcome.

The test proxy understands only plaintext MySQL packet framing for these bounded
fixtures (one MiB per packet maximum). It is not TLS, compression, multi-packet
large-value or arbitrary protocol support. Withholding bytes in a live TCP relay
is real missing-response evidence, not a claim to simulate all IP packet-loss,
NAT, asymmetric routing, timeout or production middlebox behavior.

Tmpfs proves a real bounded-filesystem ENOSPC path, not a disk/controller/fsync
failure, persistent media durability or every filesystem's failure behavior.
The namespace child uses `unshare --kill-child=KILL` to retain descendant ownership
if its launcher dies; normal exit explicitly unmounts after database cleanup.

Migration-process termination stays deferred while #477 changes that contract.

## JSONL evidence and gates

Schema version 1 shares the service evidence envelope:

- `environment`: revision, dirty state, Python/OS/architecture, PID, installed
  distributions and selected scenario. Source helpers are included in the revision;
  raw latency bucket metadata is inherited but these drills do not time throughput.
- `engine`: actual engine version, capacity and effective Transaction deadline;
  selected acquisition/health/durability/transport settings as applicable.
- `fault`: observable placement proof described above, not just a requested switch.
- `summary`: emitted **only after successful recovery, close, and owned fault-control
  cleanup**, with pool snapshots and scenario-specific outcomes/reconciliation.
- `failure`: nonzero exit and exception class when the drill fails. Absence of a
  successful summary means no pass. An isolation rejection is
  `NamespaceUnavailableError`; it is not storage evidence. Retain stderr too.

Normal CI runs `tests/test_fault_drills.py`: native stream/commit/restart scenarios
and metadata, plus the storage CLI contract. That storage contract accepts either
real success **or an explicit nonzero isolation rejection**, since some hosts deny
user namespaces. It never accepts an unexpected child/SQLite error as rejection.
Thus a passing ordinary suite alone does **not** certify storage fault coverage.
The manual **Real fault drills** workflow is stricter: each selected CLI scenario
must actually succeed, and failure/unavailable fails that workflow target. It
retains per-trial raw evidence even on failure and changes no host policy to make
namespaces work. Use a namespace-capable runner for a passing storage target.

Developer tests:

```sh
TMPDIR="$root/tmp" PYTHON_CONTEXT_AWARE_WARNINGS=1 \
  uv run snektest tests/test_fault_drills.py tests/mariadb/test_stream_faults.py \
  tests/runtime/test_raw_failures.py tests/runtime/test_raw_validated_lifecycle.py
```
