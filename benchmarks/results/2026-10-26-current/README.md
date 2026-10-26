# Current-baseline evidence, findings compiled 2026-10-26

Measurements were captured on 2026-10-25 UTC; each JSON preserves its actual
recorded_at. Source revision: `0bb5ab1ff0d2a47b9aa017e621d293f0d2b7aff1`.
All 86 reports identify that clean revision, the same lock, interpreter,
dependency versions and native engine settings.

## Files and inclusion rule

- `manifest.json`: exact sequential command vectors, reproduction environment,
  exit status, wall duration, per-run host load/memory/pressure context and
  `coverage_accepted`. Source/measurement schema versions are distinct.
- Each run has `.json`, `.stderr` (empty) and `.status` (`0`). The manifest's
  `file` identifies the report; sibling names identify stderr/status.
- **76 accepted runs / 1,368 adapter trials** enter `summary.csv`. Ten original
  eight-worker stream commands had only four operations and therefore only four
  workers with work. They are retained with `coverage_accepted: false`, never
  rewritten. Ten `-active8` replacements have 16 operations and all eight workers
  complete work. Both versions passed their actual return-value/work contract.
- `summary.csv`: descriptive summaries by backend/case/profile/counting/adapter;
  six trials per ordinary group, twelve for each on/off contrast. Medians of
  per-trial p99/max/peak statistics are not pooled percentiles or confidence bounds.
  Acquisition p99 is queue admission for raw/snekql, checkout for Core; not the
  same interval. Memory/diagnostic timing is not primary timing.
- `host-start.json`, `host-end.json`, `host-initial-matrix-end.json`, `storage.txt`:
  uncontrolled-host context, not evidence of workload/host isolation. This agent
  did not run a local suite/build concurrently; unrelated host/worktree activity
  was not isolated or exhaustively audited.
- `validation/`: commands/revisions/statuses and compressed raw validation logs.
  Focused and full local validation are separate from these measured trials.
  Full local suite: 4,155 passed; focused lazy test runner: 106 passed (CLI
  subprocesses do not automatically inherit -X). `direct-lazy/` retains 16
  successful raw/snekql direct probes, eight failed all-adapter probes and the
  failing SQLAlchemy-only reproducer. See #558; none is primary timing evidence.
  GitHub workflows were manually disabled; no new GitHub CI pass is implied.
- `development/`: failed and intermediate TDD/diagnostic evidence, not clean
  baseline success. A timed-out partial comparative suite is not a full-suite pass.
  The temporary lower-floor experiment is superseded by the explicit completed-
  burst implementation. `service-old-admission-*` probes returned zero even with
  the historical notification fix removed; filenames containing `red` do not
  convert those into failing-before evidence. Original #540 evidence is separate.
  The fix was restored before committing/measuring. The cancelled #546 CI attempt
  contained a test failure but not its final traceback; its successful target-only
  rerun is distinct. Neither is #555 CI validation.
- Native temporary databases are disposable and not committed. Native error logs
  and complete operator logs remain in the run-owned local cache after cleanup.

## Check integrity

From this directory:

```sh
sha256sum -c SHA256SUMS
```

`SHA256SUMS` covers every retained evidence file except itself. The parent findings
report is outside this manifest; the Git commit records that document separately.

## Reproduce accepted commands

Use a fresh clean worktree at the measured revision, matching CPython 3.15.0,
native MariaDB 13.0.2 tools and the locked dependencies. Native tools are required,
not silently installed or skipped. A fresh output directory and TMPDIR must be
outside the source tree so output does not make source provenance dirty.

Keep an absolute copy/path of this manifest when changing worktrees. From the
clean measured checkout after `uv sync --python 3.15.0 --locked --all-extras`:

```sh
root=$(mktemp -d "$HOME/.cache/snekql-baseline-replay-XXXXXXXX")
mkdir "$root/tmp" "$root/output"
MANIFEST=/absolute/path/to/manifest.json OUTPUT="$root/output" \
TMPDIR="$root/tmp" PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run python - <<'PY'
import json, os, subprocess
from pathlib import Path
manifest = json.loads(Path(os.environ["MANIFEST"]).read_text())
assert subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() == manifest["revision"]
assert subprocess.check_output(["git", "status", "--porcelain"]) == b""
output = Path(os.environ["OUTPUT"])
for entry in manifest["runs"]:
    if not entry["coverage_accepted"]:
        continue
    report = output / entry["file"]
    assert not report.exists(), "never overwrite prior evidence"
    with report.open("wb") as stdout, report.with_suffix(".stderr").open("wb") as stderr:
        result = subprocess.run(entry["command"], stdout=stdout, stderr=stderr)
    report.with_suffix(".status").write_text(f"{result.returncode}\n")
    if result.returncode:
        raise SystemExit(f"failed {entry['file']}; retain all output")
PY
```

Inspect and compare the resulting environment, engine/policy, command and clean
source metadata before comparing timings. Native/server globals beyond the
reported fields are not exhaustively enumerated. Changing engine/interpreter,
dependencies, storage or source creates a new baseline, not an isolated snekql
before/after claim. No timing percentage is a CI gate or universal capacity bound.
