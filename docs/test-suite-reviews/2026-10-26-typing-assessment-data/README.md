# Typing-assessment reuse evidence — 2026-10-26

Source baseline: `74c4216032e55bfbfb45cab551926b1b96388179`.
Measured candidate: `94220e1eabb52a98e220f71bac17fed5efc08f79`.
Historical evidence through `d71b39c` adds documentation only. Integration at
`93daf7b6e15201c48d03153550904fd729e5c917` then preserves main #561's support
and consumers; its only code delta from main is two end-to-end tests. Historical
measurements and full validation are not re-labelled as integration results.
`validation/integration/` records **182 normal + 182 forced-lazy** focused passes
and repeated private-copy mutant calibration at that exact source revision.
There is no newly claimed complete 4,175-case run.

- `matched.json`: exact commands, cwd/revision, fresh TMPDIR, wall time, load,
  per-file reported duration, case names and report hashes. Profile order is
  before/after, then after/before; `reports/` contains all eight exact outputs
  and stderr files. Do not interpret per-test cached durations as standalone cost.
- `inventory.json`: identical 171-case inventory, the 60 shared consumers and
  two additional default-suite regression cases. The remaining nine original CLI
  cases and 102 mutable-input challenges are not cached.
- `inputs.json`, `environment.json`: revision-pinned source/template/lock digests
  and interpreter/dependency versions. CLI, templates and library semantics do not
  change in this slice.
- `calibration/`: exact copied-source hashes, real focused-runner commands, three
  deliberate mutants, rejected-mutant reports and restored passing proofs. No
  production/test internals were mocked. Mutations stayed in owned copied inputs.
- `validation/`: full normal suite (4,166 passes), forced-lazy focused runner
  (173 passes), static commands/status/logs, and the separately retained failed
  tmpfs full attempt (4,049 passes / 42 failures / 75 errors, exit 1).
  `/tmp` uses usrquota; native installer diagnostics include allocation error 122.
  The failed run is not green evidence or a comparable full-suite timing.
- `validation/*cleanup.json`: owned-root accounting/inactivity before removal.
  No native `.err`/`.log` remained in either full root; native installer error text
  is preserved in the failed report. Empty local log archives are not included.
- `initial-baseline.json`, `initial/`: two earlier unchanged baseline observations
  (50.20 / 47.10 seconds). These use the uv CLI rather than the matched direct
  interpreter command, so they are retained but not substituted into the table.
- `archived-json.json`: uncompressed SHA-256 digests for byte-preserving gzip JSON
  archives. `SHA256SUMS` covers all packet files except itself.

Verification from this directory:

```sh
sha256sum --check SHA256SUMS
```

Use `gzip -dc validation/disk-full.json.gz` or the failed-run archive to inspect
complete raw case outcomes. The commands, revisions and profiles in `matched.json`
are the reproducibility record; scratch capture scripts and the superseded
multiple-case CLI experiment remain at `/home/crpier/.cache/sq536.7nRxfTOj/`.
The final CLI is unchanged. See [the findings](../2026-10-26-typing-assessment.md)
for contract mapping, focus commands and measurement limits.
