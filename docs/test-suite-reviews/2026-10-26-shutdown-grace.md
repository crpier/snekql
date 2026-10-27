# Isolated-clock shutdown-grace check — 2026-10-26

Tracking: #570, under #536; PR #573. This is one shutdown-wait slice, not
completion of the broader database-setup checkpoint.

## Scope

Baseline source: `63a6c72f0c66a26b2cb5e0aac534aa07a4a7de7d`.
Measured candidate: `9422d1206508c6ea1f57de5aa70946282482871e`.

The named `terminate_resistant_server_is_killed` test formerly spent ten real
seconds waiting for the documented TERM grace. It already used real executable
stand-ins rather than a native MariaDB server. The replacement retains that
public temporary-server and owned-process seam, adds an isolated controlled-clock
probe, and leaves **every library file and both ten-second shutdown budgets
unchanged**. There is no new configuration setting or application-facing API.

All other test/control definitions in the lifecycle module are AST-identical.
All 19 original runtime case names remain in default discovery. The touched
subprocess case is correctly marked `slow` instead of `medium`; an unfiltered
run still executes it. This local correction does not complete #572's marker audit.

## Observable protection

The parent test executes a fresh Python probe process and checks its JSON:

| Outcome | Independent expected value / protection |
| --- | --- |
| Actual TERM receipt | The child's installed signal handler acknowledges TERM without exiting |
| Survives through logical second 9 | Child is still running and no KILL was sent before the grace expires |
| KILL at logical second 11 | Advancing past the documented second-10 deadline causes a real OS-group SIGKILL |
| Server return code | Actual `-9`, not a synthetic successful reply |
| All children reaped | Recorded immediately when the public context returns, before rescue/fallback awaits |
| Watchdog unused | Real-time rescue cannot make missing helper cleanup look successful |

The controlled clock is installed only inside the probe's event loop. Startup
and the child readiness/TERM-file handshakes use real time. Once the child is
ready, time freezes; after actual TERM receipt the driver advances to 9 and then
11. Public timer barriers let earlier deadlines run before each observation.
No internal helper stop function, constant or timer queue is read or patched by
the normal test. OS process creation/signalling are the same external test seam
used by the original executable-stand-in case.

The child, readiness client and database-creation client are real subprocesses.
Their transport exit statuses are captured before fallback cleanup. A separate
real-time watchdog owns failed probes; all captured children are killed/reaped
on exit. Watchdog intervention is explicitly a failed lifecycle observation,
even if it eventually produces return code `-9`. The parent has its own untouched
real-time watchdog as a further bound. The altered clock never enters snektest's
shared event loop.

This checks a logical deadline bracket (alive at 9, escalation after crossing 10
at 11), not arbitrary precision of the exact deadline. It is POSIX signal evidence
with executable stand-ins, not new native MariaDB wall-clock shutdown, detached
process-tree, platform-matrix or leak-freedom qualification. Native and AnyIO
cancellation, primary-error preservation and real reset/startup checks remain in
the rest of the unchanged lifecycle module.

## Red/green and fault calibration

The replacement parent first failed because its probe did not exist; the new
probe made that named public integration test pass. This is integration TDD,
not a claim of a historical library shutdown defect.

Private copied-source calibrations then checked:

1. **Premature TERM grace:** change only the first wait from ten to one second,
   retaining the kill/reap budget. The child is killed at logical 9 and the
   survival assertion fails.
2. **Missing KILL:** omit escalation. The real-time watchdog rescues the child;
   the parent rejects the missing helper KILL observation.
3. **Premature ownership release:** omit stop/reap entirely. The real TERM receipt
   never arrives, the probe fails boundedly and its fallback cleans the child.
4. **Rescue laundering guard:** withhold the probe's actual group-KILL delivery.
   The watchdog then supplies real KILL/reaping. All reported success fields
   except `watchdog_fired` match, and the test rejects that observation. Removing
   only the watchdog assertion makes this faulty case pass; restoring it rejects
   the rescue. This deliberate false-positive control is calibration, **not a
   passing lifecycle run**.

Every copied source was restored byte-for-byte, restored checks passed, and no
process referencing the private fault TMPDIR remained. A preliminary mutant
shortened both waits and was rejected via cleanup failure; it is retained locally
but superseded by the isolated first-wait mutation above, not misrepresented as
proof of that assertion's sensitivity.

Separately, **20 ordinary + 20 direct forced-lazy probe invocations** passed every
expected OS/clock outcome with empty stderr. Direct probe mode is independent of
any forced-lazy parent runner: subprocess children do not automatically inherit
`-X`.

## Matched measurements

| Profile | Before, two runs (s) | After, two runs (s) |
| --- | ---: | ---: |
| Focused command wall time | 10.306 / 10.254 | 0.297 / 0.304 |
| Complete 19-case lifecycle file wall time | 136.980 / 93.861 | 129.611 / 106.568 |
| Target case duration inside the complete file | 10.027 / 10.029 | 0.083 / 0.088 |

Every focused run passed its one original case; every file run passed all 19
original names, with zero failures, errors or function/session teardown failures
and empty stderr. The focused command removes almost ten seconds of wall wait.

**The full-file observations do not demonstrate a speedup:** the first paired
comparison improved, the second regressed, and their two-run means do not favor
the candidate. Native lifecycle/setup variability and unisolated host activity
dwarf this one removed wait. Do not turn the focused reduction into a file-level
or whole-suite percentage claim.

Profiles used fresh processes and short private Btrfs TMPDIRs in the order
before/after, then after/before. Both revisions used the same absolute interpreter
and installed dependency environment; no uv sync or editable-metadata swap was
performed between worktrees. Warning context was set at startup, normal signal
dispositions restored, and tracked checkouts remained clean. Commands, source
identities, load snapshots, case inventories and hashes are retained.

This agent ran no other suite/build during captures. The host and other agents'
work were not isolated; two observations per condition do not establish a stable
percentile or a full-suite percentage improvement. Whole-case durations combine
setup, body and cleanup and are not native bootstrap/teardown phase profiles.

Earlier unchanged observations used the uv command rather than the matched
absolute-interpreter command: target 10.252 / 10.256 s, complete lifecycle file
94.221 / 93.910 s, all passing. They remain in the packet as preliminary evidence,
not substitutions for the matched table.

## Validation and ownership

- Matched ordinary candidate: two 19-case file runs and two focused-case runs passed.
- Forced-lazy runner: all 19 lifecycle cases passed, zero failures/errors or
  function/session teardown failures, empty stderr (83.859 s; correctness only,
  not a matched timing comparison).
- 20 ordinary and 20 **direct** forced-lazy probe runs passed.
- An additional direct probe passed in an owned transient user scope capped at
  **5% CPU**, with no rescue; this ran only after all matched captures. This
  is one constrained correctness check, not a scheduling/platform guarantee.
- `uv run ty check`, `uv run ruff check .`, `uv run ruff format --check .`,
  `uv lock --check` and `git diff --check` passed.
- Identical case inventories, source/control audit and raw-result hashes verified.
- Short owned TMPDIRs were empty (apart from an occasional empty uv lock in the
  preliminary uv-command captures), checked inactive, then removed. The detached
  before worktree was removed after captures; raw evidence was retained.

There is **no new complete-suite run** at this candidate. Earlier complete-suite
evidence for typing work is not transferred to this change, nor does a local
lifecycle pass certify remote/native-version matrices or new MariaDB shutdown
semantics. The report/evidence commit adds no further executable-code change.

No comparative-benchmark harness, dependency, migration, application API or
workflow-setting changes were made. Actions remain intentionally disabled and unawaited. Repeated database
construction is still outstanding in #570; no application schema was replaced by
a direct-model shortcut or cached migrated state. #564 remains with its assigned
agent. No merge/release/publication is implied by this report.

## Reproduce

```sh
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest \
  tests/testing/mariadb/test_process_cleanup.py

PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest \
  tests/testing/mariadb/test_process_cleanup.py::terminate_resistant_server_is_killed

PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run python -X lazy_imports=all \
  scripts/run_lazy_tests.py tests/testing/mariadb/test_process_cleanup.py --json-output

uv run python -m tests.testing.mariadb.shutdown_probe
uv run python -X lazy_imports=all -m tests.testing.mariadb.shutdown_probe
```

The [evidence packet](2026-10-26-shutdown-grace-data/README.md) contains source,
command/inventory mapping, raw results, deliberate-fault outcomes and checksums.
