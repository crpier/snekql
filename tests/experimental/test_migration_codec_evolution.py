"""Actual replaced application codecs cannot reinterpret already frozen bindings."""

import json
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from snektest import Param, assert_eq, load_fixture, test

from tests.experimental.test_migration_authoring_journey import _python, _typecheck
from tests.experimental.test_migration_targets import provide_package_server

_FIXTURES = Path(__file__).parent / "fixtures" / "codec-evolution"


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value=b, name=b)
        for b in ("sqlite", "mariadb")
    ],
    mark="slow",
)
async def frozen_v1_bindings_deploy_after_codec_replacement_and_v2_requires_explicit_rewrite(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Wire history stays v1; current-codec validation/authoring cannot certify old rows."""
    server = (
        await load_fixture(provide_package_server()) if backend == "mariadb" else None
    )
    with TemporaryDirectory() as directory:
        root = Path(directory)
        author = root / "author"
        deploy = root / "deploy"
        app = root / "app"
        for path in (author, deploy, app):
            path.mkdir()
        config = (
            {"database": str(root / "app.db")}
            if server is None
            else {
                "database": server.config().database,
                "host": server.config().host,
                "port": server.config().port,
                "user": server.config().user,
                "password": server.config().password,
                "unix_socket": str(server.config().unix_socket),
                "charset": server.config().charset,
            }
        )
        for source in _FIXTURES.glob("*.py.in"):
            if source.name.startswith("role_codec"):
                continue
            text = (
                source.read_text()
                .replace("BACKEND", backend)
                .replace("NATIVE", repr(backend == "mariadb"))
                .replace(
                    "CONFIG",
                    'db.Config(database=Path(payload["config"]["database"]))'
                    if backend == "sqlite"
                    else 'db.Config(**payload["config"])',
                )
            )
            destination = (
                deploy
                if source.name == "runtime.py.in"
                else app
                if source.name == "app.py.in"
                else author
            )
            (destination / source.name.removesuffix(".in")).write_text(text)
        codec = author / "role_codec.py"
        codec.write_text((_FIXTURES / "role_codec_v1.py.in").read_text())
        old = json.loads(await _python(author / "author.py"))
        assert_eq(old["epoch"], "v1")
        assert_eq(old["bindings"][1:3], [["admin", True], ["user", False]])
        frozen = (author / "002_roles.json").read_text()
        codec.write_text((_FIXTURES / "role_codec_v2.py.in").read_text())
        evolved = json.loads(await _python(author / "evolve.py"))
        assert evolved["candidate_digest"] != old["digest"]
        assert_eq((author / "002_roles.json").read_text(), frozen)
        for name in ("models.py", "role_codec.py"):
            shutil.copyfile(author / name, app / name)
        code, diagnostics = await _typecheck(root, author)
        assert_eq(code, 0, msg=diagnostics)
        for name in ("001_accounts.json", "002_roles.json"):
            assert_eq(
                (author / name).read_text(), (_FIXTURES / backend / name).read_text()
            )
            shutil.copyfile(_FIXTURES / backend / name, deploy / name)
        shutil.copyfile(author / "003_codec.json", deploy / "003_codec.json")
        shutil.rmtree(author)
        await _python(
            deploy / "runtime.py",
            {"action": "apply", "config": config, "package": "001_accounts.json"},
        )
        await _python(deploy / "runtime.py", {"action": "seed", "config": config})
        historical = json.loads(
            await _python(
                deploy / "runtime.py",
                {"action": "apply", "config": config, "package": "002_roles.json"},
            )
        )
        assert_eq(
            historical["wire"], [{"id": 1, "role": "admin"}, {"id": 2, "role": "user"}]
        )
        assert_eq(historical["digest"], old["digest"])
        assert_eq(
            [p[:2] for p in historical["progress"]],
            [["001_accounts", "complete"], ["002_roles", "complete"]],
        )
        assert_eq(historical["lazy_imports"], sys.get_lazy_imports())
        assert_eq(
            json.loads(
                await _python(app / "app.py", {"action": "probe", "config": config})
            ),
            {
                "epoch": "v2",
                "verified": True,
                "readable": False,
                "matches": [],
                "encoded_true": "administrator",
            },
        )
        rewritten = json.loads(
            await _python(
                deploy / "runtime.py",
                {"action": "apply", "config": config, "package": "003_codec.json"},
            )
        )
        assert_eq(rewritten["again"], "already_applied")
        assert_eq(rewritten["progress"][:2], historical["progress"])
        current = json.loads(
            await _python(app / "app.py", {"action": "read", "config": config})
        )
        assert_eq(
            current["wire"],
            [
                {"id": 1, "role": "administrator"},
                {"id": 2, "role": "member"},
                {"id": 3, "role": "administrator"},
            ],
        )
        assert_eq(current["logical"], [[1, True], [2, False]])
