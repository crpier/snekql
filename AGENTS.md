# AGENTS.md

## GitHub workflow

- Use the `gh` CLI for GitHub interactions: issues, PRs, comments, labels, and repo metadata.
- Do not hand-edit GitHub URLs or assume issue state; query with `gh issue view/list` when needed.
- Implementation work should reference the relevant GitHub issue.

## Testing and validation

- Use `snektest` for tests.
  - Look up the installed distribution metadata for `snektest` using `importlib.metadata.distribution("snektest").read_text("METADATA").` The README.
- Use `pyright` for static typing validation.
- Preferred validation commands:

  ```bash
  uv run snektest
  uv run pyright .
  ```
