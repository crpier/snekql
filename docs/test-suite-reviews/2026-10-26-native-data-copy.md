# Stopped native-data copies for password tests — 2026-10-26

Tracking: #570, under #536; PR #575. This is a measured test-only pilot, not a
change to library initialization or migration semantics.

## Scope and source

Baseline: `c7aee1611fdcef7c6ef92ffcf6489596fd7daa8b` (includes merged #573).
Clean executable candidate: `45441add9485250eff8f2009bb71a3127f1cdd5b`.
The subsequent report/evidence commit changes no executable code.

`tests/testing/mariadb/data.py` exposes one session-scoped fixture returning a
`Path -> None` copy factory. The native public temporary-server context prepares
one new data directory, including an empty `test` database. It applies **no
application migrations**. The seed server fully stops/reaps before the factory
becomes available. Each consumer receives ordinary independent files under its
own owner and starts its own native server and complete password bootstrap.
No hard links, shared live server, shared mutated inputs, migrated application
schema/history snapshot, model-direct shortcut or cross-run cache is used.

Among existing tests, only the **12 Python password-literal cases** use it. Their names, parameter
values, user/SQL-mode/password combinations, markers and all original assertions
are retained. The **four CLI cases are AST-identical and still initialize cold**.
The Python copies already contain an empty `test` database; the four cold CLI
cases and default-start controls retain initialization and missing-database
creation coverage. Their independently real CLI startup, credential/SQL-mode
behavior, redaction, connection and SIGINT/exit-130 checks remain. Default discovery adds three named
native regression cases; no existing test moves outside the default suite.

The application's shared MariaDB fixture already amortizes native setup, resets
per consumer and replays actual migrations. It and every library/default/API,
lockfile and migration implementation remain untouched. Other installer, default
fresh-start, fault and cancellation cases remain genuine cold controls. The pilot
is deliberately not applied indiscriminately to tests of initialization itself.

## Evidence before choosing a seam

At the unchanged baseline, complete password-module commands passed 16 cases in
113.987 / 127.167 s, while the public-server module passed nine in
25.726 / 24.697 s. These preliminary commands are separate from the matched
sample below, not additional candidate comparisons.

A separate transparent OS/public-operation diagnostic exercised fresh insecure
TCP, retained insecure TCP and fresh password/Unix-socket workflows twice each.
Every sample reset, connected, replayed a real two-entry chain, verified its
history/data and closed three times: **18 actual replays**, never cached output.

- Fresh native installer lifetimes: **8.262–9.387 s**.
- Fresh insecure context entry: **9.038 / 8.807 s**; retained-directory entry
  with reset: **0.666 / 0.653 s**.
- Fresh password entry: **10.330 / 10.038 s**.
- Final native shutdown: **0.120–0.200 s**; password-bootstrap shutdown
  separately **0.073–0.082 s**. Shortening public grace defaults was unjustified.
- Explicit reset: about **0.011–0.131 s**; two-entry real replay:
  **0.102–0.220 s**. Replay is preserved, not replaced by a snapshot.

This is representative instrumented phase evidence, not exact phase attribution
inside the uninstrumented cases. Retained-directory restart is **not** a benchmark
of the new copy factory. The scripts, source identities and raw events distinguish
these scopes.

## Ownership, cancellation and storage tradeoffs

The factory uses synchronous `shutil.copytree`: the shared loop is blocked during
copying, but no background writer can outlive the seed's fixture owner after
native/AnyIO task cancellation. This is a deliberate test-only interface tradeoff,
not an example of nonblocking production IO. The seed is opaque to callers and is
only read by the factory. Existing destinations raise `FileExistsError` rather
than silently reusing or overwriting caller-mutated data.

Consumers use the existing artifact owner so their native contexts exit before
successful-root cleanup; propagated failure retains owned artifacts. Seed setup
and shutdown use the unchanged public temporary-server ownership/cleanup contract.
The seed persists until session-fixture teardown. Abrupt process termination and
uninterruptible OS IO still cannot promise total cleanup/deadline bounds.

The earlier working data directories reported approximately **143 MiB** each via
`st_blocks`. A long-lived seed is real additional storage, and copies require
resources too. Filesystem copy-on-write may share extents while retaining logical
write isolation; summed `st_blocks` values are not unique physical-space or quota
headroom measurements. The isolation proof can hold two copies in addition to the seed; budget for
those resources on non-COW filesystems too. No mount/quota changes, hard-link
optimization or external copy utility is introduced. A narrow cold run pays for seed preparation plus an
extra native server start/stop and **does not get faster** in this sample.

## Protection and calibrated faults

The first integration test failed to collect before the copy-fixture module
existed, then passed with the new factory. This is test-helper integration TDD,
not reproduction of a historical library defect. The subsequent regression
guards were first exercised against plausible copied-source faults and then the
unchanged correct candidate; all restored native checks passed.

| Named protection | Actual observations / rejected private-copy fault |
| --- | --- |
| `data_copies_isolate_schema_history_and_accounts` | First copy replays and verifies a real chain, reads seeded value 42 and creates a grant account; next copy has neither application tables/history nor that account |
| Schema/history independence | A symlink alias leaks `copy_probe` and `snekql_migrations`; empty-schema assertion rejects it |
| System-account independence | Hard-linked native files leak the actual account (`n=1`, expected 0); the grant oracle rejects it even where a path-only check would pass |
| `seed_is_reaped_before_factory_publication` | Public OS-process observations require a real seed server and terminal exit status before callers receive the factory; publishing while live is rejected |
| `data_copy_rejects_existing_destinations` | An existing copied directory and caller marker must not be overwritten; `dirs_exist_ok=True` is rejected |

The tests also require `mysql` to exist **before** launching each copied server,
so replacing the factory with a no-op and silently reinstalling cold is not a
valid positive result. No private library stop/timer/database internals are mocked.
All mutation sources were confined to a private checkout, restored byte-for-byte,
and rechecked. Failed owned data was checked inactive and removed only after
archiving native logs byte-for-byte with hashes; failed reports remain evidence,
not passing runs.

## Matched measurements

| Command profile | Before, two runs (s) | After, two runs (s) |
| --- | ---: | ---: |
| Original 16-case password file | 172.432 / 165.585 | 72.914 / 59.870 |
| One original cold Python password case | 11.081 / 8.105 | 11.577 / 11.966 |

Every file command passes the same 16 original names; every narrow command passes
exactly the original `[ordinary, worker, mixed]` node. All have zero failures,
errors, function/session teardown failures and empty stderr.

**The file is faster in both pairs; the cold single case is slower in both.**
The new interface is a batch-work tradeoff, not a universal latency improvement.
The extra native seed context/start/stop and copying are not hidden or adaptively
bypassed by inspecting private runner selection.

A separate instrumented run of the real 12-case Python group observed **one
native installer and 25 helper-launched native server processes (seed plus each
case's two-stage
password bootstrap), and 12 copies from one stopped source**. All observed children were
reaped and all 12 cases passed. Counts cover the helper's direct process launches,
not the native installer's own descendants. Copy calls took 0.0046–0.0133 s on this
Btrfs host; each reported 142.70 MiB of `st_blocks` allocation. These
are diagnostic observations, not portable throughput floors or unique physical
space measurements. Other filesystems may incur substantially different cost.

The exact same original 16-case file and one original node were selected in both
clean revisions, using the same absolute interpreter/dependencies and fresh short
private Btrfs TMPDIRs. Ordering was before/after then after/before per profile,
with normal signals and startup warning context. Source/lock hashes, complete
case inventories, commands, raw reports, environment/load snapshots and statuses
are retained. Temporary data accounting/removal occurs outside command wall time.

No other suite/build was launched by this agent during captures. Other host/agent
activity, CPU frequency and filesystem contention were not isolated. Two pairs
are descriptive local evidence, not statistical or CI/platform guarantees. The
preliminary unchanged sample above and instrumented diagnostic are **not** folded
into this table.

The file comparison includes the same original **16 cases**, including four cold
CLI cases, and session setup/teardown. It **excludes the three new default-suite
regression cases**; their additional native work is included in full validation,
not hidden as a free improvement. No whole-suite before/after percentage follows
from this focused result or from a single unpaired full-suite validation run.

## Validation

- **4,245 complete-suite ordinary cases passed**, 1145.538 s.
- **87 MariaDB-helper forced-lazy cases passed**, 303.874 s.
- **3 restored copied-source cases passed**, 22.703 s.

All three validation commands had zero failures/errors or function/session
teardown failures and empty stderr.

- Normal full validation contains all original 16 password names and all three
  new default-scope regression names. Forced-lazy validation selects the entire
  MariaDB-helper directory (87 cases), including the new fixture/guards and
  original cold installer/process/CLI checks. Child Python CLIs do not inherit
  the parent's `-X`; this is not a claim of child forced-lazy execution.
- Instrumented 12-case cache-use check passes; all four deliberate source faults
  are rejected, copied sources restored and native logs preserved before removing
  inactive failed roots.
- `uv run ty check`, `uv run ruff check .`, `uv run ruff format --check .`,
  `uv lock --check`, `git diff --check`, original-contract audit and raw report
  hashes pass.
- All capture/validation TMPDIRs were checked inactive and removed after resource
  teardown. Development uv-lock-only roots were removed after the same ownership
  check. The detached before worktree was removed; source/provenance remains.

The full run is **unpaired correctness evidence**, not a new comparative suite
baseline. It validates the executable revision above; the report commit adds
only documentation/evidence and does not imply a second complete-suite run.

No remote/native-version matrix claim. Actions remain intentionally disabled and
unawaited. #570/#536 stay open; this is a narrow pilot, not proof that all remaining
database construction should share data. No merge/release/publication is implied.

## Reproduce

```sh
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest \
  tests/testing/mariadb/test_password_literals.py --json-output

PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest \
  'tests/testing/mariadb/test_password_literals.py::password_authenticates[ordinary, worker, mixed]' \
  --json-output

PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest \
  tests/testing/mariadb/test_data_copy.py --json-output

PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run python -X lazy_imports=all \
  scripts/run_lazy_tests.py tests/testing/mariadb --json-output
```

[Evidence packet](2026-10-26-native-data-copy-data/README.md): provenance, complete
reports, original-contract audit, diagnostics, calibration sources and checksums.
