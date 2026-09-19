# Archived comparison studies

All six snekql versus SQLAlchemy studies live here together. Research is paused.
These are historical snapshots, not current package tests or claims about the
latest implementation. No study-specific branches are needed.

| Study | Report | Former issue / PR |
|---|---|---|
| Relationships and schema declarations | [schema_comparison/README.md](schema_comparison/README.md) | 353 / 354 |
| Money, timestamps, defaults, and schema ergonomics | [commerce/README.md](commerce/README.md) | 355 / 357 |
| Equivalent application contracts | [contracts/README.md](contracts/README.md) | 358 / 360 |
| Updates, failure recovery, and corrupted reads | [recovery/README.md](recovery/README.md) | 363 / 365 |
| Concurrent updates and optimistic conflicts | [concurrency/README.md](concurrency/README.md) | 366 / 368 |
| Related-data loading and pagination | [loading/README.md](loading/README.md) | 369 / 374 |

## What is preserved

Each study directory contains the original tracked files from its PR head, without
rewriting code, observations, reports, tests, SQL artifacts, or dependencies.
Original issue references and reproduction instructions remain historical text.
The research issues are being deleted and their PRs closed, not merged.

`history/manifest.json` records the source commits, original bases, former branches,
and SHA-256 hashes of all 137 study files. Each matching `history/<study>/` contains:

- Issue body and comments, PR body, comments, reviews, and changed-file metadata.
- Paginated issue/PR timelines and inline review comments.
- The complete binary-capable patch against the original base commit.
- Original `pyproject.toml`, `uv.lock`, and CI configuration.

`history/cleanup.json` records completed GitHub and branch cleanup actions.
The archive itself is based on main commit
`cbe96f37d1f6064a036da0b4acb254ff79b224d5`.

The older migration-interface research, product roadmap, implementation issues,
and unrelated PRs are outside this cleanup.

## Reproduction and normal development

The reports describe the versions and checkout code used when each study ran.
Later package changes can invalidate old API calls or findings. Consolidation did
not rerun these experiments and does not claim compatibility with current main.

For exact historical source, create a detached checkout of a study's `source_base`
from the manifest, then apply its `history/<study>/changes.patch` with `git apply`.
That restores the original study plus its original project configuration without
requiring a dedicated research branch. Follow that study's report for dependencies,
Python warning settings, database binaries, and commands. Applying the patch to
current main is not a supported reproduction procedure.

Normal CI runs `uv run snektest tests`; typing and Ruff exclude this historical
archive. Comparator dependencies are not added to the current project or lockfile.
For normal local package tests, also use the explicit `tests` path rather than
recursively collecting archived research tests.
