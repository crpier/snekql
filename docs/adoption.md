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
uv init --bare --python 3.15
uv add 'snekql[aiosqlite]'
cat > smoke.py <<'PY'
import asyncio
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
    UtcDatetime,
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
    created_at: GenCol[UtcDatetime] = Text(default=CurrentTimestamp)


MIGRATIONS = {
    "0001_create_user": (
        'CREATE TABLE "user" ('
        '"id" INTEGER PRIMARY KEY AUTOINCREMENT, '
        '"email" TEXT NOT NULL, '
        '"created_at" TEXT NOT NULL DEFAULT '
        "(strftime('%Y-%m-%dT%H:%M:%f', 'now') || '000Z')"
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
            email = await tx.fetch_one(select(User.email))
            assert email == "alice@example.com"


asyncio.run(main())
PY
uv run python smoke.py
uv add --dev ty==0.0.84
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
6. Open a release PR against `main`, with exact candidate/artifact hashes and
   completed validation reports. Do not merge, choose/create a release tag, publish,
   or create a published GitHub release without explicit maintainer authorization.
7. The human maintainer runs `uv publish` after approval. Actions are currently
   maintainer-disabled: do not request/poll them, wait for unrun jobs, or claim
   automated attestations. A retained release workflow is not permission to use a
   second publishing path. Never reuse tags or publish a version twice.
8. After authorized publication, smoke-test the actual distributed package outside
   the checkout. Record its hashes/provenance and the dated changelog entry; do
   not describe a local candidate as an already published release.

### Additional recorded-migration candidate checks

The [recorded guide](recorded-migrations.md) and
[recorded recovery guide](recorded-migration-recovery.md) describe a bounded opt-in
experimental contract. Engineering acceptance is not publication approval or a
stable namespace/ABI promotion. Before including it in a release:

- Keep raw-SQL usage/recovery supported and routed separately. Publish the separate
  target requirement and absence of history conversion/stamping/cutover.
- Include both guides and their linked recipe resources in wheel and sdist;
  rebuild the wheel from the sdist and check resource/skill parity, release stamps,
  preserved example bytes, and local links. Source-only proposals are not consumer
  instructions and must not be silently shipped as such.
- Run `uv run snektest tests/packaging --json-output` and the forced-lazy equivalent
  using `scripts/run_lazy_tests.py tests/packaging --json-output`. The installed
  recorded recipe must actually generate/type-check historical bindings, reject
  stale intent, deploy without authoring imports, retain original evidence before
  application, and read/write the final representation through ordinary models.
- Retain exact-source runtime qualification and finite environment provenance.
  Re-run affected evidence after runtime or program changes; an old report does
  not automatically certify a changed candidate. State which inputs are unchanged
  when reusing evidence. No blanket patch/OS/transport/upgrade/power-loss promise.
- Explain the pre-opening lifetime, fresh bounded post-exit joins, primary-error
  precedence, and live-loop supervision obligations. Publish original-plan,
  historical-source/codec, metadata-authority and writer-exclusion responsibilities.
- Keep the existing version unchanged during documentation-only candidate work.
  Local archives with that metadata are **candidates**, not evidence that those
  bytes or guides were distributed with an earlier published version.

## Adoption expectations

For explicitly selected owned schema and typed intermediate backfills, evaluate
[recorded packages](recorded-migrations.md) separately. They are experimental and
narrower than the ordinary raw-SQL/query workflow below, not a new default or an
automatic history migration.

Security reports use the private process in [`SECURITY.md`](../SECURITY.md).
When enabled, CI is configured to reproduce the full validation and artifact smoke path on Python 3.15 with a
live rolling MariaDB 12 server. Native release jobs are configured to run the full suite on
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

- automatic live-schema diffing or unreviewed table alteration;
- automatic table creation from models (schema comes only from migrations);
- sync database access.

[All guides](README.md)
