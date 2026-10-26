# MariaDB test-artifact ownership verification — 2026-10-26

Tracking: #542, under the test-suite maintenance work in #536. The earlier
[baseline](2026-10-25-baseline.md) established repeated retained-data growth; #549
separately fixed readiness waits that hid early setup failures.

## Change and preserved contracts

`temporary_mariadb_server(runtime_base_directory=...)` creates a unique private
runtime subdirectory below an existing caller-owned base. It contains logs, PID
and default socket paths, plus default data. The CLI exposes the same control as
`--runtime-base-directory`. The public helper still retains these files after
shutdown and failed startup. Explicit external data and socket paths are not
moved or deleted. A destructive data reset cannot contain its own runtime base.

Repository fixtures and benchmark/fault/soak commands now have explicit outer
owners, with filesystem cleanup following child/resource teardown. Existing
explicit `.snektest/mariadb-data` and `.snektest/bench-mariadb-data` reuse remains
unchanged; those directories are outside the new owners. Concurrent MariaDB
commands against the same checkout remain unsupported: execute them sequentially.

The small repository-only owner in `benchmarks/_artifacts.py` deletes successful
roots, but conservatively retains roots on propagated errors, including possible
child-cleanup failures. Exception notes report private paths, not sensitive log
contents. This is not automatic pruning or runner-aware retain-on-failed-test:
fixtures cannot infer a test outcome that the runner does not propagate into
their teardown. Intentionally retained failed roots still need explicit
inspection/cleanup. Generic outcome-aware support remains in crpier/snektest#97.

Expected failing benchmark subprocesses have their own test-owned temporary
roots, so a successful test that verifies a failed command does not accumulate
the command's deliberately retained evidence.

## Regression strategy

The agreed seams are the public server helper and comparative benchmark CLI.
Red/green checks covered the missing runtime-root control, domain-error reporting
for an unusable base, retained benchmark directories on successful workloads,
the CLI flag, and a destructive-reset/runtime-base conflict. Six new public-helper
cases and one benchmark startup-failure case protect ownership, independent
servers, external-data reuse, retained failure evidence and safe invalid inputs.

Existing benchmark adapter/backend checks retain their workload assertions; no
old test names, decorators/parameterizations or assertion expressions were
removed from modified files. No Hypothesis budget, marker selection, migration
construction, shutdown grace or readiness budget was reduced.

## Complete-run verification

All commands used `PYTHON_CONTEXT_AWARE_WARNINGS=1`. Detached launchers restored
SIGINT, SIGQUIT and SIGHUP defaults. Sources/environment stayed fixed within each
measurement. Counts and hashes are in the accompanying
[environment and verification data](2026-10-26-artifact-ownership-environment.json).

| Run | Source base | Mode | Passed | Wall seconds | Retained MariaDB artifacts |
| --- | --- | --- | ---: | ---: | --- |
| 1 | `5d16b4e` + feature worktree | Normal | 4,137 | 416.68 | None |
| 2 | Same frozen worktree | Forced lazy imports | 4,137 | 463.17 | None |
| 3 | `2238a46` + feature worktree | Normal, after latest CLI security integration | 4,139 | 465.72 | None |

Every run had zero test errors/failures and zero function/session fixture
teardown failures. The first pair used the **same private TMPDIR without any
cleanup between commands**, with identical case inventories. After each command,
the only remaining entry was the same zero-byte uv lock file: no database, log,
PID or socket directories remained. The final run again left only that lock file.
The final count adds the two generated-password CLI cases from newer main; no
previous case disappeared.

Commands:

```sh
PYTHON_CONTEXT_AWARE_WARNINGS=1 TMPDIR="$owned_root" uv run snektest tests --json-output
PYTHON_CONTEXT_AWARE_WARNINGS=1 TMPDIR="$owned_root" \
  uv run python -X lazy_imports=all scripts/run_lazy_tests.py tests --json-output
```

The roots were short private directories on `/dev/shm` tmpfs, selected because
`/tmp` was quota-constrained. After recording contents and confirming no live
owned MariaDB processes, the outer roots were removed. That final removal did
not hide artifacts: per-command observations were taken first.

These are cleanup/correctness checks, **not a full-suite speedup claim**.
Workstation contention, storage and the codebase differ from the earlier baseline.

## Other validation and discoveries

- Final seam selection: 15 passed. Broader intermediate focused run: 222 passed.
- After incorporating main's password-redaction change, all 84 MariaDB support
  cases passed. The artifact audit found two newly added CLI cases still leaving
  logs; supplying their runtime bases fixed that. The CLI selection then passed
  all three cases, and complete run 3 verified the final combined tree.
- A fresh final wheel was installed outside the checkout. Both copied native
  driver contracts passed, importing the installed package, with no retained
  artifacts. The self-contained fixture owns its files without importing any
  repository-only benchmark support.
- Strict typing, lint, formatting and generated-interface checks passed.
- An earlier `/tmp` attempt produced 188 passes, six failures and 28 errors;
  initialization reported InnoDB error 122. These results were not counted as
  successful validation or attributed to a product regression. A private tmpfs
  rerun passed, without changing test expectations. Failed-run logs/manifests
  were preserved before removing only verified inactive, audit-owned roots.

Raw JSON reports, build/install logs and preserved diagnostic evidence are local
under `/home/crpier/.cache/sq542-own-GyrWsM`; the checked-in metadata pins raw
report and final build hashes. CI still needs to validate its actual PR head on
its supported OS/database matrix; local results do not certify those environments.
