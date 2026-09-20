# Failure coverage and environment evidence

This inventory starts from the existing tests. It distinguishes a real database
fault from a simulated lost reply or synthetic cursor. Passing a test does not
prove behavior under every network, filesystem, or process failure.

## Existing deterministic coverage

Paths below are relative to the repository root. Test names identify focused
cases within each file; use `uv run snektest path::name` to reproduce one.

| Failure | Existing evidence | Mechanism and limit |
| --- | --- | --- |
| Active MariaDB disconnect | `tests/mariadb/test_connection_policy.py::checkout_health_does_not_replay_active_transaction`; `tests/runtime/test_failure_classification.py::killed_mariadb_connection_has_portable_category` | Real `KILL CONNECTION` after checkout. The active transaction fails without replay; later work can obtain a new connection. This is not an in-flight stream disconnect test. |
| Server restart | `tests/mariadb/test_connection_policy.py::restarted_server_gets_configured_replacement` | Stops and starts an owned real server on the same port. A pool containing an old idle socket obtains a configured replacement. No claim about recovering an active transaction. |
| Lost COMMIT reply | `tests/runtime/test_commit_outcome.py::lost_acknowledgement_leaves_committed_write_unknown` | Both real backends commit a write, then a native-driver method raises before returning acknowledgement. Public Commit Outcome remains unknown; a later transaction observes the durable write. This models the acknowledgement boundary, not packet loss. |
| Commit interrupted or cleanup failed | `tests/runtime/test_commit_outcome.py::interrupted_mariadb_commit_is_unknown`; `restoration_failure_does_not_erase_commit_acknowledgement`; `interrupted_sqlite_close_preserves_observed_acknowledgement` | Native-driver faults preserve the distinction between acknowledged commit, unknown outcome, and connection safety. |
| No blind commit retry | `tests/runtime/test_transaction_retry_example.py::transient_category_does_not_authorize_commit_replay` | The example refuses replay based only on a transient-looking error category when commit evidence does not permit it. |
| SQLite migration interruption | `tests/sqlite/test_migration_units.py::cancellation_between_statements_rolls_back_unit`; `tests/sqlite/test_migrations.py::sqlite_body_rolls_back_when_history_insert_fails` | Real schema/data/history changes with controlled interruption. The owned migration transaction rolls back the whole unit. |
| MariaDB partial DDL | `tests/mariadb/test_migration_recovery_example.py::pending_history_can_have_committed_ddl`; `reviewed_replay_records_history_after_restart`; `acknowledged_server_commit_is_not_replayed_after_lost_reply` | Real implicit DDL commits with native-driver history/acknowledgement faults. Recovery inspects persisted state through a new Database. The test's “restart” means reconnecting the Database, not restarting the server process. |
| Migration lock cancellation | `tests/mariadb/test_migration_locking.py`; `tests/sqlite/test_migrations.py::cancellation_during_sqlite_writer_lock_acquisition_discards_connection` | MariaDB lock-policy tests include fake lock connections; SQLite exercises a real contended writer. Do not call the whole group a server-failure test. |
| Contention timeout and cancellation | `tests/runtime/test_raw_lifecycle.py::raw_deadline_discards_blocked_connection`; `raw_native_cancellation_releases_pool_capacity` | Real conflicting transactions on both backends. Timeout or cancellation prevents unsafe reuse and subsequent work completes. |
| Early stream exit and consumer failure | `tests/mariadb/test_runtime.py::mariadb_runtime_closes_stream_cursor_on_early_break`; `mariadb_runtime_closes_stream_cursor_on_consumer_exception` | Real server-side cursors are cleaned up and a following operation succeeds. |
| Late cursor fault | `tests/runtime/test_failure_classification.py::late_cursor_failure_keeps_classification` | Patches public aiosqlite cursor fetch/close methods against a real Database. Classification survives and the transaction becomes unusable. MariaDB coverage is in `tests/mariadb/test_stream_faults.py`: a native SSCursor loses its fetch or close reply after a delivered batch. The transaction becomes unusable, its lease is discarded, and a size-one pool serves later work. These are simulated replies, not packet loss. |
| Raw completion and validation failure | `tests/runtime/test_raw_execution.py::stream_completion_rejects_additional_results`; `tests/runtime/test_raw_validated_lifecycle.py` | Real result-set completion and controlled validation/cleanup faults. Additional results cannot silently leave a reusable protocol state. Some other raw-failure cases use synthetic adapter cursors, not native network faults. |
| Detached SQLite physical cleanup | `tests/runtime/test_pool_telemetry.py::discarded_connection_holds_capacity_until_close`; `tests/sqlite/test_close_failures.py::failed_discard_cleanup_remains_owned` | A public native close method is delayed or fails. Occupied admission capacity includes detached cleanup; failed cleanup remains owned for retry. |
| Shutdown races | `tests/sqlite/test_close_cancellation.py`; `tests/mariadb/test_shutdown.py` | Repeated cancellation, simultaneous closers, delayed physical close, and failed cleanup. New work stays rejected while shutdown remains incomplete. |
| Child-process leaks | `tests/testing/mariadb/test_process_cleanup.py::cancellation_reaps_owned_children`; `terminate_resistant_server_is_killed` | Cancellation at spawn/bootstrap/reset stages retains child ownership. Terminate-resistant children are killed and reaped. These tests do not measure long-run file-descriptor or RSS trends. |
| Observer cancellation and resource ownership | `tests/runtime/test_pool_telemetry.py`; `tests/runtime/test_query_telemetry.py` | Callback interruptions during admission, checkout, driver work, materialization, transaction exit, and streams do not abandon leases. Public snapshots and subsequent operations provide evidence. |

## Minimum-version regression found by this inventory

The first full run against the pinned MariaDB 12.2.2 image crashed a server with
signal 11 during `Database.verify`. The failing statement joined
`INFORMATION_SCHEMA.KEY_COLUMN_USAGE` to `REFERENTIAL_CONSTRAINTS`. The existing
`legacy_not_null_schema_is_not_rewritten` test reproduces it by itself, even
though its table has no foreign keys. The old example-only minimum-version job
never exercised this inspection path.

Verification now reads the two catalogs separately and correlates actions by
table and constraint identity, preserving member order. Missing action metadata
raises `SchemaError`, including under warn policy; it cannot certify a match.
`tests/mariadb/test_catalog_consistency.py` exercises this missing-metadata case
through `Database.verify` with fault injection at the public native cursor.
The regression test fails against the baseline and passes with the fix.

The first container also lacked the legacy `US/Eastern` timezone alias. Test
provisioning includes Ubuntu's `tzdata-legacy` package. A missing timezone dataset
is an environment failure, not a passing timezone compatibility result.

## CI targets in this part

- `Validate` runs the full suite on Ubuntu 24.04 with CPython 3.14 and the MariaDB
  12 rolling repository. It also runs typing, lint, generated-interface, lock,
  build, and isolated artifact checks.
- `MariaDB <release>` installs native server/client tools for 10.11, 11.4,
  11.8, 12.2 and 12.3, verifies the selected series, and runs the same full suite.
  The [release/capability matrix](mariadb-support.md) distinguishes maintained
  LTS targets from the retained 12.2 compatibility regression target.
  An example against a shared Docker service cannot exercise the tests that own
  and restart server processes. Those tests need the target's native binaries.
- All MariaDB jobs record effective Python, SQLite, OS, and MariaDB versions. Repository
  targets select a release series, not a permanently pinned patch build. Preserve
  the CI logs when comparing failures across dates.
- Tests run sequentially within each process. Do not run separate suite processes
  concurrently against the same MariaDB fixture data directory.

## Supported environment targets

The compatibility gates use GIL-enabled CPython 3.14.2 and standard asyncio.
Python 3.14 is the package minimum. Later Python releases, free-threaded builds,
uvloop, and Trio are not certified by this matrix. Both database drivers depend
on asyncio; using AnyIO internally does not make Trio a supported driver loop.

| Backend | OS target | Database/library target | Event loop |
| --- | --- | --- | --- |
| MariaDB | Ubuntu 24.04, x86-64 | 10.11, 11.4, 11.8, 12.3 LTS; 12.2 compatibility; 12 rolling | asyncio default |
| SQLite | Ubuntu 24.04, x86-64 | 3.45.1 from the system library, setup-python CPython | asyncio default |
| SQLite | Ubuntu 24.04 | 3.50.4 bundled with uv-managed CPython | asyncio default |
| SQLite | macOS 15 | 3.50.4 bundled with uv-managed CPython | asyncio default |
| SQLite | Windows Server 2025 | 3.50.4 bundled with uv-managed CPython | asyncio default, Proactor |

Each SQLite job asserts the **loaded** SQLite version and reports OS,
architecture, Python, and loop class. Changing a library search path cannot prove
which SQLite a statically linked Python uses. Version drift fails provisioning
until the matrix and documentation are reviewed. These are tested targets, not a
promise covering every intermediate SQLite release or every OS distribution.
SQLite 3.37 introduced the STRICT/table-list features this library needs, but
3.37 is not a tested support floor. Older SQLite builds may work; this matrix does
not certify them. Keep distributor security updates installed.

Both MariaDB jobs run the full suite, which includes the shared SQLite runtime
contracts. The additional SQLite environments run every `tests/sqlite` case plus
selected shared contention, cancellation, and detached-cleanup contracts. They do
not claim to run every shared-runtime case. Do not substitute `--mark medium` for
this selection: existing marker groups also contain MariaDB tests.

The locked development `tzdata` dependency supplies named zones on platforms
without a system timezone database, especially Windows. It does not change the
package's runtime dependency policy.

## Reproducing deterministic checks

Use Python 3.14+, the locked development dependencies, and native MariaDB tools
from the release series under investigation:

```sh
uv sync --locked --all-extras
mariadbd --version
uv run python -c 'import platform, sqlite3, sys; print(sys.version); print(platform.platform()); print(sqlite3.sqlite_version)'
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest
```

For local machines with a quota-limited system temporary directory, use a
private owned directory and retain the logs:

```sh
root=$(mktemp -d "$HOME/.cache/snekql-faults-XXXXXXXX")
mkdir "$root/tmp"
TMPDIR="$root/tmp" PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest >"$root/tests.log" 2>&1
status=$?
printf '%s\n' "$status" >"$root/status"
printf 'Results: %s\n' "$root"
```

Only remove that run's temporary directory after its processes have exited. Do
not clean unrelated MariaDB directories to make room for a run.

For focused investigation:

```sh
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest tests/runtime/test_commit_outcome.py
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest tests/runtime/test_raw_lifecycle.py
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest tests/sqlite/test_migration_units.py
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest tests/mariadb/test_migration_recovery_example.py
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest tests/testing/mariadb/test_process_cleanup.py
```

## Reproducing the SQLite environment gate

From a source checkout, provision the interpreter shown in the matrix. Use
`uv sync --locked --all-extras --python /path/to/python` for a system-library
interpreter, or `uv python install 3.14.2` followed by
`UV_PYTHON_PREFERENCE=only-managed uv sync --locked --all-extras --python 3.14.2`
for the bundled target. Verify `sqlite3.sqlite_version` before running:

```sh
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest tests/sqlite \
  'tests/runtime/test_raw_lifecycle.py::raw_deadline_discards_blocked_connection[sqlite]' \
  'tests/runtime/test_raw_lifecycle.py::raw_native_cancellation_releases_pool_capacity[sqlite]' \
  tests/runtime/test_pool_telemetry.py::discarded_connection_holds_capacity_until_close
```

The command uses a POSIX shell, including Git Bash on Windows. The GitHub matrix
uses the same selectors. An environment failure is a failed gate, not a skipped
backend.

## Optional resource soak

Long runs are separate from PR correctness checks. From a Linux source checkout,
with native MariaDB tools installed for the MariaDB target:

```sh
(
set -eu
mkdir -p "$HOME/.cache"
root=$(mktemp -d "$HOME/.cache/snekql-soak-XXXXXXXX")
mkdir "$root/tmp"
printf 'Results: %s\n' "$root"
uv sync --locked --all-extras
uv run python -c 'import platform, sqlite3, sys; print(sys.version); print(platform.platform()); print(sqlite3.sqlite_version)' >"$root/environment.txt"
mariadbd --version >>"$root/environment.txt"
git rev-parse HEAD >>"$root/environment.txt"
uv pip freeze >>"$root/environment.txt"
for backend in sqlite mariadb; do
  status=0
  TMPDIR="$root/tmp" PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run python -m soak.lifecycle --backend "$backend" --cycles 10000 >"$root/$backend.jsonl" 2>"$root/$backend.stderr" || status=$?
  printf '%s\n' "$status" >"$root/$backend.status"
  [ "$status" -eq 0 ] || exit "$status"
done
)
```

Each run owns its databases and, for MariaDB, a private temporary server. Cycles
open a size-one pool, cancel a queued waiter while its owner holds the lease,
leave a stream after its first batch, and close the database. Every cycle checks
public admission counts and closed state. A warm-up precedes the baseline. Every
100 cycles, and at the end, JSON samples report process file descriptors,
threads, and peak RSS in KiB. Descriptor or thread growth above the warmed-up
baseline fails the run. Peak RSS is reported, not thresholded: it is a high-water
mark affected by allocator retention, not a direct live-object leak measurement.
Server-process memory is not measured by these samples.

`--cycles` accepts 1 through 100000; each database cycle has a ten-second deadline.
The separate **Resource soak** workflow is manual-only, has a 45-minute job
limit, runs SQLite and both MariaDB targets independently, and retains samples
and environment metadata for 14 days. The deterministic suite includes only a
two-cycle CLI smoke check. No long soak runs during ordinary test discovery.

Keep stdout samples, stderr, exit status, commit, interpreter version, and native
server version together. Do not average away a failed cycle. A clean run is
bounded evidence for that workload; it is not a proof of universal leak freedom.
Process cleanup under cancellation and kill escalation remains covered by the
separate deterministic process-helper tests in the inventory. Performance
benchmarks and noise-aware comparisons are separate work, not correctness gates.
