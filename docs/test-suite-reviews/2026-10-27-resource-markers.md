# Resource markers: real typing assessments — 2026-10-27

Refs #572 and #536. First bounded correction, **not completion of the resource
inventory or a reduction in unfiltered suite work**.

## Scope and seam

Base: `e8eda1ab0f7b1c27c9fc34433e678ee9f9f1c89c` (merged #584).
Executable candidate: `e96ff3146bbc7dfc58fccddd82e17c8d5495e915`.
The subsequent report commit changes only contributor documentation and evidence.

Only **15 decorator literals** change, from `fast` to `slow`, in
`tests/test_typing_compatibility.py`. The **21 expanded cases** all permit
subprocess use: six definitions invoke Python/checker commands directly; nine
others load `provide_typing_assessment`, whose cold session setup launches the
real CLI through `anyio.run_process`. Reading a warm shared report is not evidence
that a cold independently selected consumer needs no external resources.

All function bodies, assertions, fixtures, parameters, names and budgets remain
identical. Every other pre-existing tracked input is unchanged at the executable
candidate. No library, framework, dependency, lock, workflow, database construction
or migration change. In particular, `tests/test_typing_assessment.py` retains its
six fast definitions/eight expanded pure report cases and its one slow real
checker case. Constructing a literal `CompletedProcess` value is not spawning a
process.

The maintainer confirmed the public **snektest CLI filters, `--mark`, and JSON
reports** as the seam before these checks were written. Selection checks catch
wrong routing, lost parameter cases and vacuous group success. They do not prove
actual resource use for all tests: that requires source/fixture review, including
cold paths. Source/AST preservation is a separate change audit, not a product
implementation-shape test.

## Routing protection

For each of the 15 producers, sequentially:

1. Run the real two-file `--mark fast` command. The producer's original cases are
   present, so the independent no-checker-in-fast expectation is **red** while
   all existing case assertions still pass.
2. Change that producer's marker literal only. Repeat the public fast command:
   the producer leaves and all eight literal-report controls remain healthy.
3. Run its cold named `--mark slow` command. All original parameter cases execute
   and pass; shared-fixture consumers really prepare their own checker report.

The red is a routing-spec failure, **not** a discovered type-system/product defect
or a failing checker assertion. One-off CLI proof scripts and reports are evidence;
no recursive self-running default-suite test or second maintained checker is added.

| Same two files | Before | After |
| --- | ---: | ---: |
| Unfiltered named cases | 61 | 61 |
| `--mark fast` | 29 | 8 |
| `--mark slow` | 32 | 53 |

The full named sets match, marked partitions are disjoint, and their union is the
unchanged 61-case inventory. The new fast set is exactly the eight known literal
report cases, not merely an arbitrary count of eight. Original negative/positive
controls, diagnostic rules/locations and infrastructure assertions are untouched.

Two source mutations in an owned private worktree calibrate the routing oracle:

| Private fault | Actual CLI result | Independent expectation |
| --- | --- | --- |
| Restore checker-backed `readiness_report_retains_checker_limits` to fast | Nine passing fast cases, including the extra producer | Reject extra name; fast must be the known eight |
| Demote pure `lookup_selects_the_named_backend_observation` to slow | Seven passing fast cases, missing that healthy control | Reject missing name; an empty/reduced group cannot certify correctness |

Both mutated CLI commands exit successfully: **the routing oracle rejects their
selection**, not a fabricated product failure. Correct markers are restored and
the eight-case fast group plus full 61-case group pass again. SDK inputs never
contain a mutation.

An initial calibration restored same-sized source too quickly for timestamp-based
bytecode invalidation, so a nominal restored run still selected nine cases. This
is unusable preliminary harness evidence, retained separately. Corrected
calibration deletes only the changed modules' owned bytecode before each run and
disables bytecode writes; source is restored byte-for-byte. It is not evidence of
a marker/framework defect. An earlier driver `StopIteration` on a fixture
instead of a marked test occurred before any CLI proof or source change; retained
as a separate preliminary error, not counted as a routing red.

## Full default scope and validation

- **4,267 before full normal cases passed**, 1269.804 s.
- **4,267 candidate full normal cases passed**, 1043.280 s.
- **61 focused parent forced-lazy cases passed**, 2.539 s.

All commands have zero test failures/errors and function/session teardown failures,
empty stderr and clean frozen source. Complete unfiltered inventories have the
same **4,267 unique names**; exactly the 21 mapped cases change metadata from
fast to slow. Every other case's markers are identical. The 61-case affected
selection also passes under the forced-lazy parent runner.

Typing, Ruff, formatting, generated interface, lock, whitespace, source-preservation
and raw/archive checksum checks pass. Owned capture/validation roots were checked
inactive and removed; zero-byte uv-lock-only remnants were accounted for first.
Private fault sources were restored before removing their owned worktree.

These are **inventory/correctness** captures, not a before/after runtime
optimization experiment. The before revision runs in an owned clean worktree
whose explicit reusable `.snektest` data begins absent; the candidate checkout
already has reusable data. Identical interpreter/dependencies, private Btrfs
TMPDIRs, normal signals and startup warning context do not erase that difference
or unrelated host activity. No percentage improvement follows from elapsed time.
Marker correction changes selection; it removes no unfiltered work.

Parent forced-lazy mode does not imply that child checker CLIs inherit `-X`.
No full forced-lazy suite, direct child forced-lazy, remote OS/native-version
matrix, release or long-running resource qualification is claimed.

## Initial wider resource inventory

The read-only AST inventory at the base found **2,457 decorated definitions in
298 test modules**: 1,004 fast, 830 medium, 522 slow, 101 unmarked. These are not
expanded case counts. Signals include nested function bodies and miss dynamic
calls; they are candidate discovery, not automatic resource verdicts. The pilot
changes definition counts to 989 fast / 830 medium / 537 slow / 101 unmarked.

High-confidence follow-ups need separate reviewed changes:

- Nine fast docs-CLI definitions and isolated import/help/installer checks launch
  processes even when their assertions look like string or configuration checks.
- 81 medium definitions explicitly reach the real shared MariaDB server fixture,
  sometimes only in a backend branch. More native work sits behind local fixture
  wrappers. A session cache cannot make these safe for a standalone medium run.
- Twenty fast SQLite collation/schema-fact definitions open aiosqlite databases;
  `:memory:` avoids a data file, **not the driver thread**. Source-reading and
  explicitly threaded tests also need review.
- The 101 unmarked definitions need resource classification. Do not infer a
  missing test from marker-only selections: unfiltered discovery includes them.

Keep-as-is examples prevent broad folder/name-based relabeling: MariaDB fake-pool
checks use in-process stand-ins; validation-only temporary-server calls can fail
before startup; in-process HTTP/ASGI transport is not socket IO. Pure literal
report tests remain fast. Resource declarations concern test/fixture paths, not
the common machinery needed to collect/import/report a CLI run. Markers are
permissions, not duration bands, backend selectors or an OS sandbox.

This is a partial audit. **Global `--mark fast` is not yet verified free of
misclassified external-resource consumers**; the reviewed literal-report file
selection is the bounded safe feedback loop documented here. #572 stays open.

## Initial CI overlap review — documentation only

All seven workflow files were read. Read-only repository Actions permissions
report `enabled: false`. No workflow is triggered, enabled, awaited or changed.
No dependency/tool/action upgrade or release action is part of this review.

| Configured work | Distinct protection | Overlap/disposition |
| --- | --- | --- |
| Ubuntu validate: ordinary and parent forced-lazy full suite | Default correctness versus PEP 810 import policy | Keep both; a parent flag is not proof about ordinary child CLIs |
| Five MariaDB release jobs: 10.11, 11.4, 11.8, 12.2, 12.3 | Real version-specific schema/runtime/driver behavior | Pure/SQLite/typing work repeats, but no reduction without complete backend case mapping |
| SQLite system-linked 3.45.1 and managed 3.53.1 across Linux/macOS/Windows | Linked engine, platform and event-loop behavior | Same managed SQLite number does not make OS rows redundant |
| Build and isolated installed-wheel/extra smoke tests | Consumer installation, import origin, dependency resolution and native installed-driver behavior | Future build-once artifact reuse might remove repeated builds, not fresh installs or version-specific native checks |
| Standalone consumer-assessment report | Explicit script invocation and uploadable checker evidence | Overlaps suite fixture; future report reuse must preserve CLI/diagnostic/artifact guarantees, not silently delete them |
| CodeQL and dependency review | Source-security analysis and introduced dependency risk | Not equivalent to typing/lint/runtime checks; retain distinct purposes |
| Release build/attestation/publish | Tagged artifact identity, provenance and publication | Separate maintainer-controlled release concern; not authorized here |
| Manual lifecycle/service/fault drills | Resource trends, long-lived operations and real fault evidence | Not substitutes for correctness tests or each other; remain manual |

`tests/mariadb` alone misses shared/runtime/root MariaDB paths, and `--mark slow`
is neither a backend filter nor currently a reliable replacement for the full
native contract map. Recommend **no matrix-row/check removal** in this initial
review. If later artifact reuse changes tools/actions, follow the separate
dependency-maintenance procedure first. The installed-wheel smoke's explicit
forced-lazy Python examples do not imply its separate native-driver tests run
with that flag.

## Current-main cost checkpoint

Frozen main `e8eda1ab0f7b1c27c9fc34433e678ee9f9f1c89c` passed all
4,267 cases in 1269.804 s. Its largest runner-attributed files were:

| File | Cases | Sum case seconds |
| --- | ---: | ---: |
| `tests/test_comparative_benchmarks.py` | 88 | 250.146 |
| `tests/runtime/test_migration_baseline_example.py` | 28 | 136.815 |
| `tests/testing/mariadb/test_process_cleanup.py` | 19 | 132.812 |
| `tests/testing/mariadb/test_password_confidentiality.py` | 14 | 109.813 |
| `tests/testing/mariadb/test_password_literals.py` | 16 | 58.499 |
| `tests/test_fault_drills.py` | 8 | 57.465 |
| `tests/mariadb/test_required_tls.py` | 8 | 46.369 |
| `tests/testing/mariadb/test_public_api.py` | 9 | 38.886 |

The complete ranking and 20 largest named cases are in `main-profile-files.csv`
and `main-profile.json`. Setup may be charged to a first consumer and session
teardown is not isolated in these sums. The fresh before worktree's reusable
data state is explicit; these are local prioritization observations, not clean
phase attribution, stable timing floors or a whole-suite improvement claim.

Use this fresh revision-pinned profile to choose a next investigation, not to
extend native data sharing indiscriminately. It does not reopen deferred migration
redesign, remove compatibility controls or change property budgets. If main moves
before the next optimization, check source/cost relevance again.

## Reproduce focused feedback

```sh
# Pure report ownership/copy/cardinality checks: no real checker launch.
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest \
  tests/test_typing_assessment.py --mark fast --json-output

# Real checker conformance. Static probes for both families do not start MariaDB.
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest \
  tests/test_typing_compatibility.py --mark slow --json-output

# Both kinds; all 61 cases, including independent real broken-positive evidence.
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest \
  tests/test_typing_compatibility.py tests/test_typing_assessment.py --json-output
```

The pure report checks do not prove actual inference. Compatibility tests do not
replace native execution/migration/lifecycle checks or every other typing batch.
Unfiltered `snektest tests` still runs everything by default.

[Evidence packet](2026-10-27-resource-markers-data/README.md): exact commands,
source hashes, CLI transcripts, calibration/restoration, initial inventory and
byte-preserving complete reports. Tracking #536/#572 remains open; no merge is
implied by a passing local run.
