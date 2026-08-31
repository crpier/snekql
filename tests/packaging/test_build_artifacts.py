"""Built distribution content contracts."""

from __future__ import annotations

import subprocess
from pathlib import Path
from tarfile import open as open_tar
from tempfile import TemporaryDirectory

from snektest import assert_eq, test


@test(mark="medium")
def source_distribution_contains_only_release_inputs() -> None:
    """Local caches, settings, tests, and reports stay out of the sdist."""

    project_root = Path(__file__).parents[2]
    with TemporaryDirectory() as directory:
        build = subprocess.run(
            [
                "uv",
                "build",
                "--sdist",
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
