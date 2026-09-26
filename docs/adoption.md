# Adoption and release confidence

Before depending on snekql, try the published package in a fresh environment,
check the supported database features, and decide who owns migrations in your
application. This page gives you that smoke test and the maintainer release
checklist.

New to the library? Use [getting started](getting-started.md) first. Adding it to
an application? Read the [service recipes](service-recipes.md) and
[backend differences](backend-capabilities.md). The [compatibility policy](compatibility.md)
explains what can change during 0.x and what is planned for 1.0.

## Published-package smoke test

Run this outside the repository so the local checkout cannot shadow the package
from the index.

```sh
tmpdir=$(mktemp -d)
cd "$tmpdir"
uv init --bare --python 3.14
uv add 'snekql[aiosqlite]'
cat > smoke.py <<'PY'
import asyncio
from datetime import datetime
from typing import ClassVar

from snekql.sqlite import (
    PENDING_GENERATION,
    Col,
    CurrentTimestamp,
    Database,
    Row,
    GenCol,
    Integer,
    Model,
    Pending,
    ReadType,
    Text,
    insert,
    select,
)


class User[S = Pending](Model[S]):
    __row_type__: ClassVar[ReadType[User[Row]]]
    id: GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: Col[str] = Text()
    created_at: GenCol[datetime] = Text(default=CurrentTimestamp)


MIGRATIONS = {
    "0001_create_user": (
        'CREATE TABLE "user" ('
        '"id" INTEGER PRIMARY KEY AUTOINCREMENT, '
        '"email" TEXT NOT NULL, '
        '"created_at" TEXT NOT NULL DEFAULT '
        "(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        ') STRICT'
    )
}


async def main() -> None:
    # initialize connects only; migrations remain committed literal SQL.
    async with await Database.initialize(
        database=":memory:",
        pool_size=1,
    ) as db:
        await db.migrate(MIGRATIONS)
        await db.verify_migrations(MIGRATIONS)
        await db.verify([User])
        async with db.transaction() as tx:
            await tx.execute(insert(User(email="alice@example.com")))
            email = await tx.fetch_one(select(User.email).all())
            assert email == "alice@example.com"


asyncio.run(main())
PY
uv run python smoke.py
uv add --dev ty==0.0.77
uv run ty check smoke.py
```

Expected result:

- The runtime script exits successfully.
- `ty` reports `All checks passed!`.

## Repository smoke test

Run the same high-level adoption path against the checkout:

```sh
uv run python -m examples.basic_app
uv run ty check examples/typed_queries.py
```

The first command exercises model declaration, connect-only initialization,
migrate and verify, insert, select, update, delete, transaction handling, and
close behavior. The second command verifies public result-shape typing from the
selected backend namespace.

## Release checklist

Before announcing a release:

1. Confirm `pyproject.toml` has the intended version and package metadata.
2. Confirm `CHANGELOG.md` has a dated entry for the version.
3. Run the repository validation suite:
   ```sh
   uv run snektest tests
   uv run ty check
   uv run ruff check .
   uv run ruff format --check .
   uv run python scripts/generate_query_overloads.py --check
   ```
4. Confirm the lock and generated interface are current:
   ```sh
   uv lock --check
   uv run python scripts/generate_query_overloads.py --check
   ```
5. Build and smoke-test clean artifacts:
   ```sh
   rm -f dist/*.whl dist/*.tar.gz
   uv build
   uv run python scripts/check_artifacts.py
   ```
   The script requires exactly one wheel and sdist, installs the wheel outside
   the checkout, then checks imports, CLI startup, SQLite runtime startup, and
   public typing.
6. After explicit maintainer approval, merge the release PR. Before authorizing
   publication, verify the `pypi` environment approval rules and PyPI Trusted
   Publisher configuration. The workflow's environment name alone does not
   establish that approval is required. Tag the approved exact commit as
   `v<project version>` and push the tag. Never reuse or move a release tag.
7. With publication authorization, create the GitHub release from that tag. This
   triggers the existing release workflow, not just an announcement. Its build
   job verifies tag/version equality and records a build provenance attestation.
   Its `pypi` publish job uses the same artifacts, Trusted Publishing and PyPI
   attestations. Do not also run `uv publish` for the same version. Verify the
   resulting attestations against the distributed artifacts.
8. Run the published-package smoke test above and attach the dated changelog
   entry to the GitHub release.

## Adoption expectations

Security reports use the private process in [`SECURITY.md`](../SECURITY.md).
CI reproduces the full validation and artifact smoke path on Python 3.14 with a
live rolling MariaDB 12 server. Native release jobs also run the full suite on
10.11, 11.4, 11.8 and 12.3 LTS, plus the retained 12.2 compatibility target.
They include owned-server restart and process-cleanup tests, rather than only
the public example. Each job records its Python, SQLite, OS, and MariaDB versions.
See the [MariaDB support policy](mariadb-support.md) before choosing a release.
See the [failure coverage inventory](failure-matrix.md) for evidence and limits.

snekql is a good fit when an application wants:

- explicit SQL-shaped query construction;
- typed `INNER`/`LEFT` joins across declared foreign-key relationships;
- async SQLite and MariaDB execution;
- hand-authored migrations applied with an explicit `db.migrate(...)`;
- partial structural schema verification with `db.verify(...)`;
- typed row contracts without ORM identity or relationship behavior.

snekql is not a fit when an application needs:

- autogenerated migrations or automatic table alteration;
- automatic table creation from models (schema comes only from migrations);
- sync database access.

[All guides](README.md)
