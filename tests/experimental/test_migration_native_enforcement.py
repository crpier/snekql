"""Dedicated native sessions refuse disabled integrity policy before yielding."""

from pathlib import Path
from typing import ClassVar, Literal

from pymysql.err import OperationalError
from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb
from snekql.experimental import migrations as m
from tests.experimental.test_migration_io_deadlines import NativeAccount, NativeInitial
from tests.experimental.test_migration_targets import provide_package_server


@test(
    [
        Param[
            Literal["check_constraint_checks", "foreign_key_checks", "unique_checks"]
        ](value="check_constraint_checks", name="check"),
        Param[
            Literal["check_constraint_checks", "foreign_key_checks", "unique_checks"]
        ](value="foreign_key_checks", name="foreign-key"),
        Param[
            Literal["check_constraint_checks", "foreign_key_checks", "unique_checks"]
        ](value="unique_checks", name="unique"),
    ],
    mark="slow",
)
async def disabled_native_checking_refuses_before_original_role_execution(
    setting: Literal["check_constraint_checks", "foreign_key_checks", "unique_checks"],
) -> None:
    """Refusing admission is not execution, repair or a reason to rebuild originals."""
    server = await load_fixture(provide_package_server())
    config = server.config()
    fixed = Path(__file__).parent / "fixtures" / "role-interruption" / "mariadb"
    packages = [
        m.Package.load((fixed / name).read_text())
        for name in ("001_accounts.json", "002_expand.json", "003_roles.json")
    ]
    first, expansion, roles = packages
    originals = [package.dump() for package in packages]
    async with m.connect(config) as target:
        assert_eq(
            await target.apply(
                await target.prepare(first, schema_writers_excluded=True)
            ),
            "applied",
        )
    async with (
        await mariadb.Database.initialize(config) as app,
        app.transaction() as tx,
    ):
        await tx.execute(
            mariadb.insert_many(
                NativeInitial,
                [
                    NativeInitial(id=1, is_admin=True),
                    NativeInitial(id=2, is_admin=False),
                ],
            )
        )
        saved = await tx.fetch_one(
            mariadb.raw(f"SELECT @@GLOBAL.{setting} AS value,@@GLOBAL.sql_mode AS mode")
        )
    async with m.connect(config) as target:
        assert_eq(
            await target.apply(
                await target.prepare(expansion, schema_writers_excluded=True)
            ),
            "applied",
        )
        original = await target.prepare(roles, schema_writers_excluded=True)
        wire = original.dump()
    async with (
        await mariadb.Database.initialize(config) as app,
        app.transaction() as tx,
    ):
        before = await tx.fetch_all(
            mariadb.raw(
                "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
            )
        )
    await server.run_sql(f"SET GLOBAL {setting}=0")
    try:
        yielded = False
        with assert_raises(mariadb.DatabaseRuntimeError) as error:
            async with m.connect(config) as target:
                yielded = True
                await target.apply(m.Prepared.load(wire))
        assert_eq(yielded, False)
        assert setting in str(error.exception)
        assert "1 (ON)" in str(error.exception)
        async with (
            await mariadb.Database.initialize(config) as app,
            app.transaction() as tx,
        ):
            assert_eq(
                await tx.fetch_one(
                    mariadb.raw(
                        f"SELECT @@GLOBAL.{setting} AS value,@@GLOBAL.sql_mode AS mode"
                    )
                ),
                {"value": 0, "mode": saved["mode"]},
            )
            assert_eq(
                await tx.fetch_all(
                    mariadb.raw("SELECT id,is_admin,role FROM accounts ORDER BY id")
                ),
                [
                    {"id": 1, "is_admin": 1, "role": None},
                    {"id": 2, "is_admin": 0, "role": None},
                ],
            )
            receipts = await tx.fetch_all(
                mariadb.raw(
                    "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
                )
            )
            assert_eq(receipts, before)
            assert_eq(
                [row["revision"] for row in receipts], ["001_accounts", "002_expand"]
            )
    finally:
        await server.run_sql(f"SET GLOBAL {setting}={saved['value']}")
    async with m.connect(config) as target:
        assert_eq(await target.apply(m.Prepared.load(wire)), "applied")
        assert_eq(await target.apply(m.Prepared.load(wire)), "already_applied")
        assert_eq(
            sorted((p.revision, p.phase) for p in await target.status()),
            [
                ("001_accounts", "complete"),
                ("002_expand", "complete"),
                ("003_roles", "complete"),
            ],
        )
    async with (
        await mariadb.Database.initialize(config) as app,
        app.transaction() as tx,
    ):
        await tx.execute(mariadb.insert(NativeAccount(id=3, role="user")))
        rows = await tx.fetch_all(
            mariadb.select(NativeAccount).order_by(NativeAccount.id.asc())
        )
    assert_eq([(r.id, r.role) for r in rows], [(1, "admin"), (2, "user"), (3, "user")])
    assert_eq(original.dump(), wire)
    assert_eq([package.dump() for package in packages], originals)


class ExternalParent[S = mariadb.Pending](mariadb.Model[S]):
    """Reference mapping is not permission to create/adopt the external parent."""

    __tablename__: ClassVar[str] = "reference_parent"
    __row_type__: ClassVar[mariadb.ReadType[ExternalParent[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)


class ReferencingChild[S = mariadb.Pending](mariadb.Model[S]):
    """Only this child is selected for migration ownership."""

    __tablename__: ClassVar[str] = "reference_child"
    __row_type__: ClassVar[mariadb.ReadType[ReferencingChild[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    parent_id: mariadb.FKCol[ExternalParent, int] = mariadb.ForeignKey(
        ExternalParent.id, nullable=False
    )


@test(
    [
        Param[Literal["missing", "view", "MyISAM", "MEMORY"]](
            value="missing", name="missing"
        ),
        Param[Literal["missing", "view", "MyISAM", "MEMORY"]](
            value="view", name="view"
        ),
        Param[Literal["missing", "view", "MyISAM", "MEMORY"]](
            value="MyISAM", name="myisam"
        ),
        Param[Literal["missing", "view", "MyISAM", "MEMORY"]](
            value="MEMORY", name="memory"
        ),
    ],
    mark="slow",
)
async def admitted_native_reference_cannot_complete_over_an_invalid_external_parent(
    kind: Literal["missing", "view", "MyISAM", "MEMORY"],
) -> None:
    """Engine FK rejection is not a completion receipt, implicit adoption or safe finish."""
    server = await load_fixture(provide_package_server())
    if kind == "view":
        await server.run_sql("CREATE VIEW reference_parent AS SELECT 1 AS id")
    elif kind != "missing":
        await server.run_sql(
            "CREATE TABLE reference_parent(id BIGINT NOT NULL PRIMARY KEY) ENGINE="
            + kind
        )
    package = m.Package.load(
        m.compile(m.generate("001_child", [ReferencingChild], backend="mariadb")).dump()
    )
    assert_eq([table.name for table in package.target.tables], ["reference_child"])
    async with m.connect(server.config()) as target:
        original = await target.prepare(package, schema_writers_excluded=True)
        wire = original.dump()
        with assert_raises(OperationalError):
            await target.apply(m.Prepared.load(wire))
        assert_eq(
            [
                (p.revision, p.phase, p.acknowledged_steps)
                for p in await target.status()
            ],
            [("001_child", "uncertain", 0)],
        )
        recovery = await target.inspect_recovery(
            m.Prepared.load(wire), schema_writers_excluded=True
        )
        assert_eq(
            recovery.disposition,
            "retry_remaining" if kind in {"missing", "view"} else "ambiguous",
        )
        with assert_raises(m.PackageError):
            await target.apply(m.Prepared.load(wire))
        assert_eq(original.dump(), wire)
    async with (
        await mariadb.Database.initialize(server.config()) as app,
        app.transaction() as tx,
    ):
        assert_eq(
            await tx.fetch_all(
                mariadb.raw(
                    "SELECT TABLE_NAME AS name FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='reference_child'"
                )
            ),
            [],
        )
