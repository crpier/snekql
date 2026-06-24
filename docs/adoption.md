# Adoption and release confidence

This checklist is for maintainers validating a published snekql release and for
application teams deciding whether the package is ready to adopt.

## Published-package smoke test

Run this outside the repository so the local checkout cannot shadow the package
from the index.

```sh
tmpdir=$(mktemp -d)
cd "$tmpdir"
uv init --bare --python 3.14
uv add snekql
cat > smoke.py <<'PY'
from __future__ import annotations

import asyncio
from datetime import datetime

from snekql.sqlite import (
    PENDING_GENERATION,
    CurrentTimestamp,
    Database,
    Fetched,
    Integer,
    Model,
    Pending,
    Text,
    insert,
    select,
)


class User[S = Pending](Model[S, "User[Fetched]"]):
    id: User.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: User.Col[str] = Text(nullable=False)
    created_at: User.GenCol[datetime] = Text(default=CurrentTimestamp)


async def main() -> None:
    async with await Database.initialize(
        database=":memory:",
        models=[User],
        pool_size=1,
    ) as db:
        async with db.transaction() as tx:
            await tx.execute(insert(User(email="alice@example.com")))
            email = await tx.fetch_one(select(User.email).all())
            assert email == "alice@example.com"


asyncio.run(main())
PY
uv run python smoke.py
uv add --dev pyright
uv run pyright smoke.py
```

Expected result:

- The runtime script exits successfully.
- Pyright reports `0 errors, 0 warnings, 0 informations`.

## Repository smoke test

Run the same high-level adoption path against the checkout:

```sh
uv run python -m examples.basic_app
uv run pyright examples/typed_queries.py
```

The first command exercises model declaration, schema startup, insert, select,
update, delete, transaction handling, and close behavior. The second command
verifies public result-shape typing from the package root.

## Release checklist

Before announcing a release:

1. Confirm `pyproject.toml` has the intended version and package metadata.
2. Confirm `CHANGELOG.md` has a dated entry for the version.
3. Run the repository validation suite:
   ```sh
   uv run snektest
   uv run pyright .
   uv run ruff check .
   uv run ruff format --check .
   ```
4. Build artifacts:
   ```sh
   rm -rf dist
   uv build
   ```
5. Inspect the wheel for typing support:
   ```sh
   python - <<'PY'
   from pathlib import Path
   from zipfile import ZipFile

   wheel = next(Path("dist").glob("*.whl"))
   with ZipFile(wheel) as archive:
       names = set(archive.namelist())
       assert "snekql/py.typed" in names
       assert "snekql/__init__.pyi" in names
   PY
   ```
6. Publish to the package index.
7. Run the published-package smoke test above.
8. Create and push a version tag, then create a GitHub release from the
   changelog entry.

## Adoption expectations

snekql v1 is a good fit when an application wants:

- explicit SQL-shaped query construction;
- typed `INNER`/`LEFT` joins across declared foreign-key relationships;
- async SQLite execution;
- `STRICT` table startup checks;
- typed row contracts without ORM identity or relationship behavior.

snekql v1 is not a fit when an application needs:

- migrations or automatic table alteration;
- raw SQL execution;
- sync database access;
- multiple database dialects.
