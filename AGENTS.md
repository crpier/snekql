# AGENTS.md

## GitHub workflow

- Use the `gh` CLI for GitHub interactions: issues, PRs, comments, labels, and repo metadata.
- Do not hand-edit GitHub URLs or assume issue state; query with `gh issue view/list` when needed.
- Implementation work should reference the relevant GitHub issue.
- When starting a new unit of work, first stash any uncommited changes, do a `git fetch`, then create a new branch, based on the latest `origin/main` branch.
- All work should be done in a branch, and when a unit of work is complete, open a PR against `main`. Only merge the PR if explicitly told to do so.
- When doing feature/bug-fixing/refactoring or any code-related work, use TDD.

## Testing and validation

- Use `snektest` for tests.
  - Look up the installed distribution metadata for `snektest` using `importlib.metadata.distribution("snektest").read_text("METADATA").` The README.
- Use `pyright` for static typing validation.
- Preferred validation commands:

  ```bash
  uv run snektest
  uv run pyright .
  uv run ruff check .
  uv run ruff format --check .
  ```
