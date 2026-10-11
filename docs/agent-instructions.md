# Give coding agents the installed snekql docs

Bundled documentation makes guides available offline; a project instruction makes
agents consult them when working on snekql code. Add the section below to your
consumer project's `AGENTS.md`, or the equivalent instruction file your agent
loads. This is for applications using snekql, not for contributing to snekql.

Use your project's Python environment. The snippet uses `uv run python`; replace
that with your project's Python runner if you do not use uv. The printed index
identifies the release and links to its guides. Read those resources relative to
`snekql/docs/`, not relative to your application's working directory.

## Copy into your project's instructions

````markdown
## snekql

When adding, changing, debugging, or reviewing snekql models, queries, database
lifecycles, migrations, or type annotations, read the installed release's index
and the relevant guides before choosing APIs. Use these version-matched references
rather than conventions from other query builders or latest-branch documentation.

Run with this project's Python environment:

```sh
uv run python -c 'from importlib.resources import files; print(files("snekql").joinpath("docs", "README.md").read_text())'
```

Guide names below are relative to `files("snekql").joinpath("docs")`. Read a guide
by replacing `README.md` in the command above with its filename:

- Models/columns: `models.md`, `storage.md`.
- Queries/results: `queries.md`, `results.md`, `api-reference.md`.
- Connections/transactions/shutdown: `transactions.md`, `connection-lifecycle.md`.
- Migrations/upgrades: `migrations.md`, `class-body-migration.md`, `compatibility.md`.
- Typing/backend differences: `typing.md`, `typing-compatibility.md`,
  `backend-capabilities.md`.

Follow the index for other tasks and when guide names differ. Repository-only
references require a matching source checkout; use the bundled usage guides for
API decisions.

If snekql cannot be imported, first check the project environment. For an editable
install without bundled resources, use the matching source checkout's
`docs/README.md`.
````

## Keep the instruction small

The copied section is a retrieval pointer, not a second API reference. Keep API
examples and detailed rules in the installed guides; read only the guides needed
for the current task. Re-run the index command after dependency updates so the
agent consults the newly installed version.
