"""Offline documentation contracts at the published-package boundary."""

import asyncio
import subprocess
import sys
from collections.abc import AsyncGenerator
from pathlib import Path
from re import DOTALL, findall
from shutil import copy2, copytree, ignore_patterns
from tarfile import open as open_tar
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from snektest import (
    assert_eq,
    assert_in,
    assert_not_in,
    assert_true,
    fixture,
    load_fixture,
    test,
)


def _run(command: list[str], cwd: Path | str) -> subprocess.CompletedProcess[str]:
    """Capture build and isolated-interpreter diagnostics as text."""
    return subprocess.run(command, cwd=cwd, check=False, capture_output=True, text=True)


@fixture(scope="session")
async def release_artifacts() -> AsyncGenerator[Path]:
    """Build once outside the checkout without modifying release output."""
    with TemporaryDirectory() as directory:
        for target in ("--sdist", "--wheel"):
            build = await asyncio.to_thread(
                _run,
                ["uv", "build", target, "--out-dir", directory],
                cwd=Path(__file__).parents[2],
            )
            assert_eq(build.returncode, 0, msg=build.stderr)
        yield Path(directory)


@test(mark="slow")
async def wheel_contains_current_user_guides() -> None:
    """Consumers receive a navigable index and the main reference guides."""
    artifacts = await load_fixture(release_artifacts())

    def read_entries() -> set[str]:
        with ZipFile(next(artifacts.glob("*.whl"))) as archive:
            return set(archive.namelist())

    entries = await asyncio.to_thread(read_entries)

    for name in (
        "README.md",
        "getting-started.md",
        "models.md",
        "queries.md",
        "transactions.md",
        "migrations.md",
        "recorded-migrations.md",
        "recorded-migration-recovery.md",
        "api-reference.md",
        "typing.md",
        "typing-compatibility.md",
        "backend-capabilities.md",
        "class-body-migration.md",
        "temporal-contracts.md",
    ):
        assert_in(f"snekql/docs/{name}", entries)


@test(mark="slow")
async def installed_guides_have_resolvable_local_links() -> None:
    """Resources remain readable outside the checkout, including linked recipes."""
    artifacts = await load_fixture(release_artifacts())

    with TemporaryDirectory() as directory:
        environment = Path(directory) / ".venv"
        python = (
            environment / "Scripts" / "python.exe"
            if sys.platform == "win32"
            else environment / "bin" / "python"
        )
        for command in (
            ["uv", "venv", "--python", sys.executable, str(environment)],
            [
                "uv",
                "pip",
                "install",
                "--no-deps",
                "--python",
                str(python),
                str(next(artifacts.glob("*.whl"))),
            ],
        ):
            setup = await asyncio.to_thread(
                _run,
                command,
                cwd=directory,
            )
            assert_eq(setup.returncode, 0, msg=setup.stderr)

        probe = await asyncio.to_thread(
            _run,
            [
                str(python),
                "-I",
                "-c",
                r"""
from importlib.resources import files
from pathlib import Path
import re

package = files("snekql")
docs = package.joinpath("docs")
assert "Getting started" in docs.joinpath("README.md").read_text()
assert "SQLite" in docs.joinpath("getting-started.md").read_text()
assert "repository-only" in docs.joinpath("typing.md").read_text()
for guide in docs.iterdir():
    if not guide.name.endswith(".md"):
        continue
    text = re.sub(r"```.*?```", "", guide.read_text(), flags=re.S)
    text = re.sub(r"`[^`]*`", "CODE", text)
    for target in re.findall(r"\[[^\]\n]+\]\(([^)\n]+)\)", text):
        if target.startswith(("https:", "http:", "mailto:", "#")):
            continue
        path = Path(str(guide)).parent / target.split("#")[0]
        assert path.is_file(), f"{guide.name}: {target}"
""",
            ],
            cwd=directory,
        )

    assert_eq(probe.returncode, 0, msg=probe.stderr)


@test(mark="slow")
async def source_archive_preserves_curated_docs() -> None:
    """Source distributions contain the same offline resources as direct wheels."""
    artifacts = await load_fixture(release_artifacts())

    def read_docs() -> tuple[dict[str, bytes], dict[str, bytes]]:
        with ZipFile(next(artifacts.glob("*.whl"))) as archive:
            wheel_docs = {
                name: archive.read(name)
                for name in archive.namelist()
                if name.startswith("snekql/docs/")
            }
        with open_tar(next(artifacts.glob("*.tar.gz")), mode="r:gz") as archive:
            source_docs = {}
            for member in archive.getmembers():
                name = member.name.split("/", 1)[-1]
                if member.isfile() and name.startswith("snekql/docs/"):
                    stream = archive.extractfile(member)
                    assert stream is not None
                    with stream:
                        source_docs[name] = stream.read()
        return source_docs, wheel_docs

    source_docs, wheel_docs = await asyncio.to_thread(read_docs)

    assert_in("snekql/docs/README.md", source_docs)
    assert_eq(source_docs, wheel_docs)


@test(mark="slow")
async def release_docs_exclude_repository_internals() -> None:
    """An explicit selection keeps historical and maintainer material out."""
    artifacts = await load_fixture(release_artifacts())

    def read_entries() -> set[str]:
        with ZipFile(next(artifacts.glob("*.whl"))) as archive:
            return set(archive.namelist())

    entries = await asyncio.to_thread(read_entries)

    for name in (
        "contributing.md",
        "adoption.md",
        "dependency-maintenance.md",
        "class-body-interface-proposal.md",
        "query-composition-design.md",
        "schema-compatibility-audit.md",
        "python315-native-contracts.md",
        "security-review-2026-10-10.md",
        "adr/0022-explicit-temporal-meanings.md",
        "dependency-reviews/2026-10-09-python315.md",
    ):
        assert_not_in(f"snekql/docs/{name}", entries)


@test(mark="slow")
async def rebuilding_source_archive_preserves_docs() -> None:
    """Rebuilding away from the checkout does not need the unbundled docs tree."""
    artifacts = await load_fixture(release_artifacts())

    with TemporaryDirectory() as directory:
        build = await asyncio.to_thread(
            _run,
            [
                "uv",
                "build",
                "--wheel",
                str(next(artifacts.glob("*.tar.gz"))),
                "--out-dir",
                directory,
            ],
            cwd=directory,
        )
        assert_eq(build.returncode, 0, msg=build.stderr)

        def read_docs() -> tuple[dict[str, bytes], dict[str, bytes]]:
            documents = []
            for folder in (artifacts, Path(directory)):
                with ZipFile(next(folder.glob("*.whl"))) as archive:
                    documents.append(
                        {
                            name: archive.read(name)
                            for name in archive.namelist()
                            if name.startswith("snekql/docs/")
                        }
                    )
            return documents[0], documents[1]

        direct_docs, rebuilt_docs = await asyncio.to_thread(read_docs)

    assert_in("snekql/docs/README.md", rebuilt_docs)
    assert_eq(rebuilt_docs, direct_docs)


@test(mark="slow")
async def bundled_index_identifies_its_release() -> None:
    """Offline readers can distinguish release docs from a latest-branch checkout."""
    artifacts = await load_fixture(release_artifacts())

    def read_index() -> tuple[str, str]:
        with ZipFile(next(artifacts.glob("*.whl"))) as archive:
            metadata = next(
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
            )
            version_line = next(
                line
                for line in archive.read(metadata).decode().splitlines()
                if line.startswith("Version: ")
            )
            return archive.read("snekql/docs/README.md").decode(), version_line[9:]

    index, version = await asyncio.to_thread(read_index)

    assert_in(f"Release: {version}", index)


@test(mark="slow")
async def incomplete_source_tree_cannot_build_without_docs() -> None:
    """A missing selection must not silently produce a documentation-free wheel."""
    with TemporaryDirectory() as directory:
        checkout = Path(directory)

        def copy_build_inputs() -> None:
            root = Path(__file__).parents[2]
            for name in ("pyproject.toml", "hatch_build.py", "README.md", "LICENSE"):
                copy2(root / name, checkout / name)
            copytree(
                root / "snekql",
                checkout / "snekql",
                ignore=ignore_patterns("__pycache__"),
            )

        await asyncio.to_thread(copy_build_inputs)
        build = await asyncio.to_thread(
            _run,
            ["uv", "build", "--wheel", "--out-dir", str(checkout / "dist")],
            cwd=checkout,
        )

    assert build.returncode != 0, "missing curated docs must fail the build"


@test(mark="slow")
async def bundling_preserves_code_examples() -> None:
    """Link adaptation must not rewrite fenced examples or copied recipe sources."""
    artifacts = await load_fixture(release_artifacts())

    def compare_examples() -> None:
        root = Path(__file__).parents[2]
        with ZipFile(next(artifacts.glob("*.whl"))) as archive:
            for name in archive.namelist():
                if name.startswith("snekql/docs/examples/"):
                    assert_eq(
                        archive.read(name),
                        (root / "examples" / Path(name).name).read_bytes(),
                        msg=name,
                    )
                elif name.startswith("snekql/docs/") and name.endswith(".md"):
                    source = root / "docs" / Path(name).name
                    if source.name in {"README.md", "CHANGELOG.md", "SECURITY.md"}:
                        continue
                    assert_eq(
                        findall(
                            r"```.*?```", archive.read(name).decode(), flags=DOTALL
                        ),
                        findall(r"```.*?```", source.read_text(), flags=DOTALL),
                        msg=name,
                    )

    await asyncio.to_thread(compare_examples)


@test(mark="slow")
async def release_wheel_includes_official_skill() -> None:
    """Consumers receive the library-skills discovery resource with the package."""
    artifacts = await load_fixture(release_artifacts())

    def read_skill() -> str:
        with ZipFile(next(artifacts.glob("*.whl"))) as archive:
            return archive.read("snekql/.agents/skills/snekql/SKILL.md").decode()

    skill = await asyncio.to_thread(read_skill)

    assert_true(skill.startswith("---\nname: snekql\n"))
    assert_in("description:", skill)
    assert_in('files("snekql").joinpath("docs", "README.md")', skill)


@test(mark="slow")
async def source_rebuild_preserves_official_skill() -> None:
    """The source channel retains the same skill exposed by direct wheel builds."""
    artifacts = await load_fixture(release_artifacts())
    resource = "snekql/.agents/skills/snekql/SKILL.md"

    def read_source_skill() -> tuple[bytes, bytes]:
        with ZipFile(next(artifacts.glob("*.whl"))) as archive:
            wheel_skill = archive.read(resource)
        with open_tar(next(artifacts.glob("*.tar.gz")), mode="r:gz") as archive:
            member = next(
                member
                for member in archive.getmembers()
                if member.name.split("/", 1)[-1] == resource
            )
            stream = archive.extractfile(member)
            assert stream is not None
            with stream:
                return stream.read(), wheel_skill

    source_skill, wheel_skill = await asyncio.to_thread(read_source_skill)

    assert_eq(source_skill, wheel_skill)

    with TemporaryDirectory() as directory:
        build = await asyncio.to_thread(
            _run,
            [
                "uv",
                "build",
                "--wheel",
                str(next(artifacts.glob("*.tar.gz"))),
                "--out-dir",
                directory,
            ],
            cwd=directory,
        )
        assert_eq(build.returncode, 0, msg=build.stderr)

        def read_rebuilt_skill() -> bytes:
            with ZipFile(next(Path(directory).glob("*.whl"))) as archive:
                return archive.read(resource)

        rebuilt_skill = await asyncio.to_thread(read_rebuilt_skill)

    assert_eq(rebuilt_skill, wheel_skill)


@test(mark="slow")
async def installed_skill_command_reads_matching_release_docs() -> None:
    """The skill's actual retrieval command works with only the installed wheel."""
    artifacts = await load_fixture(release_artifacts())

    with TemporaryDirectory() as directory:
        environment = Path(directory) / ".venv"
        python = (
            environment / "Scripts" / "python.exe"
            if sys.platform == "win32"
            else environment / "bin" / "python"
        )
        for command in (
            ["uv", "venv", "--python", sys.executable, str(environment)],
            [
                "uv",
                "pip",
                "install",
                "--no-deps",
                "--python",
                str(python),
                str(next(artifacts.glob("*.whl"))),
            ],
        ):
            setup = await asyncio.to_thread(_run, command, cwd=directory)
            assert_eq(setup.returncode, 0, msg=setup.stderr)

        probe = await asyncio.to_thread(
            _run,
            [
                str(python),
                "-I",
                "-c",
                r"""
from importlib.metadata import version
from importlib.resources import files
from re import search
from subprocess import run
import sys

skill = files("snekql").joinpath(".agents", "skills", "snekql", "SKILL.md").read_text()
command = search(r"uv run python -c '([^']+)'", skill)
assert command is not None
result = run([sys.executable, "-I", "-c", command[1]], capture_output=True, text=True)
assert result.returncode == 0, result.stderr
assert "# Bundled snekql guides" in result.stdout
assert f"Release: {version('snekql')}" in result.stdout
""",
            ],
            cwd=directory,
        )

    assert_eq(probe.returncode, 0, msg=probe.stderr)
