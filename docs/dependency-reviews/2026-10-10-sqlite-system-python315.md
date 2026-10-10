# System-library SQLite CI repair — 2026-10-10

Tracking: #451. Base: `564f5c2adf297ed73935e2b2656e1aae1b538aa6`.
Branch: `ci/sqlite-system-python315`.

## Baseline and scope

The system-library SQLite job on Ubuntu 24.04 failed before synchronization or
tests: `actions/setup-python` could not find Python 3.15.0 for that platform.
This happened both on security-hardening PR #450 and on its merged main commit.
The existing failed CI job is the red regression; its environment assertions and
SQLite/backend lifecycle tests are the public validation boundary. No workflow
snapshot tests, mocks, lower Python minimum, skipped job, or relaxed SQLite
assertions were introduced.

The intended lane is Python 3.15 linked to Ubuntu's SQLite 3.45.1. A managed
Python with bundled SQLite 3.53.1 would duplicate the other lane rather than
restore the missing coverage.

## Reviewed provisioning changes

| Component | Before → after | Impact / decision |
| --- | --- | --- |
| CPython | Unavailable setup-python 3.15.0 artifact → source build of the same 3.15.0 release | CI-only. Pin `python/cpython` to release commit `d220409a13b77de7a6c30abe16ea90db01528edc`, resolved with `gh api`. Configure against installed Ubuntu development libraries and install into `RUNNER_TEMP`, not a system prefix. |
| System build libraries | Implicit setup-python build provenance → explicit Ubuntu build dependencies | Preserve the system SQLite header/library pairing. SSL, compression, FFI, readline, curses, UUID and zstd dependencies keep useful standard-library modules available. No OS packages are changed on the maintainer's host. |
| actions/checkout | Existing v7.0.1 SHA reused for a conditional second checkout | No action upgrade. CPython is checked out separately; credential persistence is disabled for that source checkout. |
| actions/setup-python | Removed from this lane | No version bump or floating replacement. Other workflows are untouched. |
| uv | Workflow 0.13.0 unchanged | Supplies the locked environment using the explicit built-interpreter path. Local global uv is 0.12.22; container validation uses isolated 0.13.0, not the global installation. |
| Package dependencies and metadata | Unchanged | No lockfile refresh, compatibility-cap change, package-version change, or build-backend change. |

Sources reviewed:

- [Pinned CPython release commit](https://github.com/python/cpython/commit/d220409a13b77de7a6c30abe16ea90db01528edc),
  queried from `v3.15.0` rather than assuming a tag SHA.
- [CPython 3.15 build configuration](https://raw.githubusercontent.com/python/cpython/v3.15.0/Doc/using/configure.rst):
  native build requirements, optional-module libraries, pkg-config detection,
  installation prefix, and `--with-ensurepip=no`.
- [uv 0.13.0 release](https://github.com/astral-sh/uv/releases/tag/0.13.0),
  already reviewed in the [Python migration report](2026-10-09-python315.md).
  No new uv version interval is introduced.

The source build uses the default GIL-enabled configuration, without PGO/LTO or
an interpreter cache. This costs CI build time but avoids a cache that might
silently retain old system-library linkage after runner package changes. The
existing runtime SQLite version and GIL assertions remain unchanged and gate
execution of the backend suite.

## Validation

Local native reproduction uses a disposable Ubuntu 24.04 Docker container,
image digest
`sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55`.
It builds the pinned source using the workflow's build commands, synchronizes
all locked extras with uv 0.13.0, runs the unchanged environment assertions, and
runs the unchanged SQLite/backend lifecycle command. Only `sudo` is omitted
because the container runs as root. The source build and package environment
remain inside the container; the host project environment is not replaced.

Results:

- Container build and locked sync: passed, uv 0.13.0 and CPython 3.15.0.
- Unchanged environment assertions: passed, SQLite **3.45.1**, GIL enabled,
  Unix selector event loop.
- Unchanged lane test command: **331 passed** in 11.00 seconds. The complete
  container provisioning/build/sync/test execution took about 66 seconds on the
  local host; this is not a hosted-runner timing guarantee.
- `uv run ty check`, `uv run ruff check .`, and
  `uv run ruff format --check .`: passed, 515 Python files.
- `uv lock --check`, generated query-overload check, `git diff --check`, and
  Bash syntax check of the extracted validation commands: passed.

Logs and downloaded validation inputs are outside tracked source, under
`.git/dependency-review/`. Hosted-runner results are tracked by the PR's actual
head checks; a local container pass does not certify GitHub action execution.

No broad dependency upgrades, fresh vulnerability-advisory assessment, package
release, or performance claims are part of this targeted repair. The managed
SQLite and MariaDB lanes are unchanged; GitHub CI must validate the actual PR
head before merge. The maintainer retains merge and release decisions.
