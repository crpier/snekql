"""Built distribution content contracts."""

from __future__ import annotations

import subprocess
from pathlib import Path
from tarfile import open as open_tar
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from snektest import assert_eq, assert_in, test


@test(mark="medium")
def distributions_contain_only_release_inputs_and_typing_metadata() -> None:
    """The sdist is clean and the wheel carries its PEP 561 interface."""

    project_root = Path(__file__).parents[2]
    with TemporaryDirectory() as directory:
        build = subprocess.run(
            [
                "uv",
                "build",
                "--out-dir",
                directory,
            ],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
        )
        assert_eq(build.returncode, 0, msg=build.stderr)
        archive_path = next(Path(directory).glob("*.tar.gz"))
        with open_tar(archive_path, mode="r:gz") as archive:
            top_level_entries = {
                Path(name).parts[1]
                for name in archive.getnames()
                if len(Path(name).parts) > 1
            }
        wheel_path = next(Path(directory).glob("*.whl"))
        with ZipFile(wheel_path) as archive:
            wheel_entries = set(archive.namelist())

    assert_eq(
        top_level_entries,
        {
            ".gitignore",
            "CHANGELOG.md",
            "PKG-INFO",
            "README.md",
            "pyproject.toml",
            "snekql",
        },
    )
    assert_in("snekql/py.typed", wheel_entries)
    assert_in("snekql/__init__.pyi", wheel_entries)
