"""Same role journey with explicit ownership, preservation and non-destructive handoff."""

import json
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from snektest import Param, assert_eq, test

from tests.experimental.test_migration_authoring_journey import _python, _typecheck

_FIXTURES = Path(__file__).parent / "fixtures"


@test(
    [
        Param[Literal["plain", "extended", "dependent"]](value=m, name=m)
        for m in ("plain", "extended", "dependent")
    ],
    mark="slow",
)
async def ownership_lifecycle_keeps_query_mapping_and_external_schema_independent(
    mode: Literal["plain", "extended", "dependent"],
) -> None:
    """Plain re-adoption succeeds; preserved unmanaged additions explicitly limit it."""
    with TemporaryDirectory() as directory:
        root = Path(directory)
        for name in ("models.py.in", "backfill_revised.py.in"):
            destination = "models.py" if name == "models.py.in" else "backfill.py"
            (root / destination).write_text(
                (_FIXTURES / "account-role-workflow" / name)
                .read_text()
                .replace("BACKEND", "sqlite")
            )
        for source in (_FIXTURES / "ownership-lifecycle").glob("*.py.in"):
            shutil.copyfile(source, root / source.name.removesuffix(".in"))
        await _python(root / "stage.py")
        await _python(root / "review.py")
        code, diagnostics = await _typecheck(root, root)
        assert_eq(code, 0, msg=diagnostics)
        result = json.loads(
            await _python(
                root / "lifecycle.py", {"mode": mode, "database": str(root / "app.db")}
            )
        )
        assert_eq(result["query_only"], ["external"])
        assert_eq(result["lazy_imports"], sys.get_lazy_imports())
        if mode == "dependent":
            assert_eq(result["revisions"], ["001_adopt"])
            assert "depends on removed columns" in result["blocked"]
            return
        assert_eq(result["roles"], [[1, "admin"], [2, "user"]])
        assert_eq(
            result["revisions"],
            ["001_adopt", "002_roles", "003_handoff"]
            + (["004_readopt"] if mode == "plain" else []),
        )
        assert_eq(bool(result["readopt_refusal"]), mode == "extended")
