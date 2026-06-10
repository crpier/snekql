# AGENTS.md

## GitHub workflow

- Use the `gh` CLI for GitHub interactions: issues, PRs, comments, labels, and repo metadata.
- Do not hand-edit GitHub URLs or assume issue state; query with `gh issue view/list` when needed.
- Implementation work should reference the relevant GitHub issue.
- When starting a new unit of work, stash any uncommitted changes, run `git fetch`, then create a new branch from the latest `origin/main`.
- All work should be done in a branch, and when a unit of work is complete, open a PR against `main`. Only merge the PR if explicitly told to do so.
- When doing feature/bug-fixing/refactoring or any code-related work, use TDD.

## Release checklist

For package releases:

1. Confirm `main` is current, stash local work, fetch tags, and create a release branch.
2. Review changes since the previous version tag and choose the next version.
3. Update `pyproject.toml` version and package metadata if needed.
4. Run `uv lock` so `uv.lock` matches the package version.
5. Update `CHANGELOG.md` with a dated entry, including breaking changes.
6. Run validation:

   ```bash
   uv run snektest
   uv run pyright .
   uv run ruff check .
   uv run ruff format --check .
   ```

7. Remove stale `dist/` artifacts, then run `uv build`.
8. Inspect built artifacts and metadata under `dist/`.
9. Open a release PR against `main`; do not publish or tag unless explicitly told.
10. The human maintainer runs `uv publish`.

## Testing and validation

- Use `snektest` for tests.
  - For snektest usage documentation, read its installed distribution metadata with `importlib.metadata.distribution("snektest").read_text("METADATA")`; the `METADATA` file embeds snektest's README.
- Use `pyright` for static typing validation.
- Preferred validation commands:

  ```bash
  uv run snektest
  uv run pyright .
  uv run ruff check .
  uv run ruff format --check .
  ```
