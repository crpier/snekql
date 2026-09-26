# Review dependency updates

Run this exercise roughly every two weeks, when requested by the maintainer.
Security alerts need prompt review rather than waiting for that cadence.
The agent does the investigation, upgrades, tests, and report. The maintainer
reviews the PR. Nothing schedules updates or merges them automatically.

To start a cycle, ask:

> Review and update dependencies using docs/dependency-maintenance.md. Explain
> what changed upstream, which snekql behavior it affects, and what you checked.
> Record any held upgrades. Open a PR, but do not merge it.

## 1. Establish the baseline

Follow [AGENTS.md](../AGENTS.md) for preserving local work, fetching main,
branching, and issue tracking. Use the uv version pinned in the workflows;
record any different local version. Save logs outside tracked source directories.
The commands below assume Bash and the repository root.

```sh
review="$(git rev-parse --git-path dependency-review)/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$review"
git rev-parse HEAD > "$review/base.txt"
uv --version > "$review/uv.txt"
uv sync --locked --all-extras
uv tree --locked > "$review/before-tree.txt"
cp pyproject.toml "$review/before-pyproject.toml"
cp uv.lock "$review/before-uv.lock"
uv pip list --outdated --format json > "$review/outdated.json"
uv lock --upgrade --dry-run > "$review/proposed-lock.txt" 2>&1
uv audit --locked --output-format json > "$review/before-audit.json"
rg -n 'uses:|version:' .github/workflows > "$review/workflow-tools.txt"
```

`uv audit` needs a recent uv and currently has an experimental JSON schema.
Check its exit status and stderr. An unavailable advisory service is an incomplete
check, not a clean audit. `uv pip list` covers the installed environment, not
isolated build dependencies, action internals, or packages excluded by markers.
Review `uv.lock`, `[build-system]`, and workflows too.

Run affected existing tests and static checks before changing dependencies.
If the baseline fails, separate that failure from upgrade effects. Read snektest's
installed distribution metadata for current runner options.

Done when the baseline versions, proposed candidates, explicit pins, and affected
checks are recorded. A dry run does not assess compatibility.

## 2. Review each candidate

For every changed direct or transitive package, record:

- Locked version, candidate version, and whether it reaches installed users,
  optional extras, tests, benchmarks, builds, or CI only.
- Upstream release notes and migration notes covering the version interval.
  Check advisories, Python support, yanked releases, and dependency changes.
- Actual imports and usage in this repository. Name affected files and behavior.
- Accept or hold, with a reason and the checks needed to revisit a hold.

Use upstream sources, not the bot's summary alone. For GitHub projects:

```sh
gh release list --repo OWNER/REPO
gh release view TAG --repo OWNER/REPO --json tagName,url,body
# Also inspect intervening releases and any migration guide.
gh api --method GET advisories -f ecosystem=pip -f affects=PACKAGE@VERSION
```

Release listing order is not version order. Some repositories publish backports,
prereleases, or several products, such as CodeQL bundles alongside the action.
Check the intended product and stable release explicitly.

### Where to look for effects

| Dependency | Inspect and exercise |
| --- | --- |
| Pydantic, pydantic-core, annotated-types, typing helpers | `model.py`, `storage.py`, declaration binding, validation, generated fields, codecs, materialization, and public typing probes. Keep Pydantic's exact core dependency together. |
| AnyIO and its dependencies | Runtime deadlines, cancellation, pool admission, process cleanup, and context-local state. Run native cancellation and cleanup tests on both backends. |
| aiomysql, PyMySQL, aiosqlite | Connection lifecycle, transactions, streaming, errors, TLS, binary binding, and migration checksums. Run real databases and freshly resolved wheel extras. |
| OpenTelemetry API, SDK, semantic conventions | `snekql/opentelemetry.py`, span ancestry, metrics, cancellation, and parameter/error redaction. Upgrade coupled packages together. |
| FastAPI, Starlette, HTTPX | `examples/service_app.py` and `tests/test_service_recipes.py`. Middleware and lifespan changes can affect request-owned transactions. |
| SQLAlchemy and greenlet | `benchmarks/_comparison_*.py` and `tests/test_comparative_benchmarks.py`. Keep the asyncio extra. Correctness tests do not establish unchanged performance. |
| snektest, Hypothesis | Test discovery, fixtures, warning capture, generated cases, and shrinking. New counterexamples need investigation, not weaker assertions. |
| ty, Ruff, secondary checkers | Exact positive and negative typing controls, root typing, lint, and format. Inspect new diagnostics before fixes; keep rules and signatures intact. |
| uv, Hatchling, build dependencies | Resolver changes, lockfile compatibility, Python downloads and bundled SQLite, isolated wheel/sdist builds, fresh extras, metadata, and CLI examples. |
| GitHub Actions | Release notes, runtime/runner requirements, inputs, permissions, cache policy, and transitive actions. Validate on CI; release and soak jobs need separate execution authorization. |

Read [driver compatibility](mariadb-support.md#python-driver-compatibility)
before changing driver bounds, and [typing compatibility](typing-compatibility.md)
before changing checker pins. An upstream release number alone does not justify
removing a compatibility cap.

## 3. Upgrade in attributable groups

Start with one package or a coupled group, then run its targeted checks. Inspect
the complete lock diff because a targeted update can change transitive packages.
For example:

```sh
uv lock --upgrade-package anyio
uv sync --locked --all-extras
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest \
  tests/runtime/test_pool_cancellation_handoff.py \
  tests/runtime/test_raw_lifecycle.py

git diff -- pyproject.toml uv.lock
```

If a dependency reveals a bug, first retain a public regression that fails on
the candidate. Fix only the demonstrated incompatibility, or hold the upgrade.
Preserve old and new logs. Distinguish environment failures from product failures.

A lockfile bump need not raise a library dependency's minimum version. Change
published bounds only when the supported contract requires it. Review exact
checker pins and upper bounds separately; `uv lock --upgrade` respects them.
Avoid forcing a transitive dependency against its parent's metadata.

For actions, query the release commit and pin the full SHA with a version comment:

```sh
gh api repos/OWNER/REPO/commits/TAG --jq .sha
```

Check the SHA against the selected release. Preserve action subpaths such as
`/init`. A moving major tag defeats reviewed updates. A pinned composite action
or container can still contain moving dependencies; inspect and document them.

When upgrading uv, use an isolated tool environment rather than replacing the
maintainer's global installation. Put its `bin` directory on the validation
process's PATH so nested tool invocations use the candidate too. Verify a fresh
Python download, not just an already-installed interpreter. Keep the CI SQLite
version assertions; investigate mismatches rather than deleting them.

Done when every actual lock or workflow change has an impact decision and its
targeted checks pass. Finish with `uv lock --upgrade --dry-run` and explain any
remaining candidates.

## 4. Validate the combined result

```sh
uv sync --locked --all-extras
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest tests
uv run ty check
uv run ruff check .
uv run ruff format --check .
uv run python scripts/generate_query_overloads.py --check
uv lock --check
uv audit --locked --output-format json > "$review/after-audit.json"
uv run python scripts/check_typing_compatibility.py > "$review/ty.json"

# Unsupported checkers normally return 1 for nonconformance. Inspect reports.
# Exit 2, crashes, and malformed reports are failed assessments, not rejections.
uv run python scripts/check_typing_compatibility.py --checker pyright > "$review/pyright.json"
uv run python scripts/check_typing_compatibility.py --checker mypy > "$review/mypy.json"

rm -f dist/*.whl dist/*.tar.gz
uv build --verbose > "$review/build.log" 2>&1
uv run python scripts/check_artifacts.py --mariadb
```

Run commands separately and record their status; an expected secondary-checker
exit must not hide another failure. Build logs identify isolated build versions,
which are not covered by `uv.lock`. Fresh artifact installs test published ranges,
not just the development lock.

Run MariaDB suites sequentially. They share checkout fixtures and consume
substantial temporary space. Check quota as well as filesystem free space.
Before removing test data, establish ownership, confirm shutdown and no live
process, and preserve server logs. Do not redirect typing-test temporary files
into the checkout.

If you detach a suite, reset SIGINT, SIGQUIT, and SIGHUP to their defaults before
launching it; inherited ignored signals can invalidate subprocess tests. Avoid
editing source or resyncing the environment while validation runs.

## 5. Report and hand off

Add a dated report under `docs/dependency-reviews/` with the base revision,
version/impact table, source links, held upgrades, observed failures and fixes,
exact validation results, and untested environments. Separate runtime coverage,
typing coverage, advisory lookup, and performance claims. Include workflow SHA
and tool changes. Link the report in the PR and this guide.

Open a PR against main. CI must validate its actual head before merge; local Linux
tests cannot certify macOS, Windows, other MariaDB versions, or a release publish.
Merging, tagging, publishing, and scheduling another cycle remain human decisions.

## Automation policy

Dependabot version-update configuration is removed. Automated security-fix PRs
are disabled in repository settings. Vulnerability alerts, CodeQL, and the
pull-request dependency-review check stay enabled. These are separate controls.
Removing the configuration takes effect on main after merge.

Maintainers can verify the server-side settings with:

```sh
repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
gh api "repos/$repo/automated-security-fixes"
gh api --include "repos/$repo/vulnerability-alerts"  # 204 means alerts enabled
```

## Review history

- [2026-09-26](dependency-reviews/2026-09-26.md)
