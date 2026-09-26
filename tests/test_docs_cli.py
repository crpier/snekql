"""Docs CLI tests."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import AsyncGenerator
from textwrap import indent

from anyio import Path, TemporaryDirectory, run_process
from snektest import Param, assert_eq, assert_in, fixture, load_fixture, test


@fixture
async def provide_quick_start(source_name: str) -> AsyncGenerator[str]:
    """Copy the published first Python example without rewriting its source."""
    if source_name == "agent-docs":
        guide = await run_process(
            [sys.executable, "-m", "snekql", "--agent-docs"], check=False
        )
        assert_eq(guide.returncode, 0, msg=guide.stderr.decode())
        markdown = guide.stdout.decode()
    elif source_name == "getting-started":
        markdown = await Path("docs/getting-started.md").read_text()
    else:
        markdown = await Path("README.md").read_text()
        markdown = markdown.split("## Try it\n", 1)[1]
    yield markdown.split("```python\n", 1)[1].split("```", 1)[0]


@test(mark="fast")
def docs_cli_prints_agent_docs() -> None:
    """Consumers can print bundled usage docs from an installed package."""

    result = subprocess.run(
        [sys.executable, "-m", "snekql", "--llms"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert_eq(result.returncode, 0)
    assert_in("snekql agent guide", result.stdout)
    assert_in("from snekql import sqlite", result.stdout)


@test(mark="fast")
def docs_cli_lists_bundled_examples() -> None:
    """Consumers can discover packaged copyable examples."""

    result = subprocess.run(
        [sys.executable, "-m", "snekql", "--examples"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert_eq(result.returncode, 0)
    assert_in("basic", result.stdout)
    assert_in("typed_queries", result.stdout)


@test(mark="fast")
def docs_cli_prints_named_example() -> None:
    """Consumers can print a packaged example source file."""

    result = subprocess.run(
        [sys.executable, "-m", "snekql", "--example", "typed_queries"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert_eq(result.returncode, 0)
    assert_in("from snekql import sqlite", result.stdout)
    assert_in("select(", result.stdout)


@test(mark="fast")
def docs_cli_accepts_positional_examples_command() -> None:
    """Consumers can use snektest-style positional example listing."""

    result = subprocess.run(
        [sys.executable, "-m", "snekql", "examples"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert_eq(result.returncode, 0)
    assert_in("typed_queries", result.stdout)


@test(mark="fast")
def docs_cli_accepts_positional_example_command() -> None:
    """Consumers can use snektest-style positional example printing."""

    result = subprocess.run(
        [sys.executable, "-m", "snekql", "example", "basic"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert_eq(result.returncode, 0)
    assert_in("class User", result.stdout)


@test(mark="fast")
def docs_cli_rejects_unknown_example() -> None:
    """Unknown example names fail without running unrelated commands."""

    result = subprocess.run(
        [sys.executable, "-m", "snekql", "--example", "missing"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert_eq(result.returncode, 2)
    assert_in("Unknown example", result.stderr)


@test(mark="fast")
def docs_cli_rejects_unknown_positional_command() -> None:
    """Unknown positional commands fail instead of silently printing help."""

    result = subprocess.run(
        [sys.executable, "-m", "snekql", "nope"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert_eq(result.returncode, 2)
    assert_in("Unknown command", result.stderr)


@test(
    [
        Param("agent-docs", name="agent-docs"),
        Param("README", name="README"),
        Param("getting-started", name="getting-started"),
    ],
    mark="fast",
)
async def documented_quick_start_runs(source_name: str) -> None:
    """The printed quick start can create and read its documented SQLite row."""
    source = await load_fixture(provide_quick_start(source_name))

    async with TemporaryDirectory(prefix="snekql-docs-") as directory:
        completed = await run_process(
            [sys.executable, "-c", source],
            cwd=directory,
            check=False,
        )

    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
    assert_eq(completed.stdout.decode().strip(), "alice@example.com")


@test(
    [
        Param("agent-docs", name="agent-docs"),
        Param("README", name="README"),
        Param("getting-started", name="getting-started"),
    ],
    mark="slow",
)
async def documented_quick_start_has_exact_row_type(source_name: str) -> None:
    """Copied model declarations retain Pending construction and Row read results."""
    source = await load_fixture(provide_quick_start(source_name))

    async with TemporaryDirectory(prefix="snekql-docs-typing-") as directory:
        caller = Path(directory) / "quick_start.py"
        await caller.write_text(
            source
            + """
from typing import assert_type

assert_type(User(email="ada@example.com"), User[sqlite.Pending])

async def check_result(transaction: sqlite.Transaction) -> None:
    assert_type(
        await transaction.fetch_all(sqlite.select(User).all()),
        list[User[sqlite.Row]],
    )
"""
        )
        checked = await run_process(
            [sys.executable, "-m", "ty", "check", str(caller)], check=False
        )

    assert_eq(
        checked.returncode, 0, msg=checked.stdout.decode() + checked.stderr.decode()
    )


@test(mark="slow")
async def readme_preview_has_exact_row_type() -> None:
    """The short opening example keeps the result type promised beside it."""
    quick_start = await load_fixture(provide_quick_start("README"))
    markdown = await Path("README.md").read_text()
    preview = markdown.split("```python\n", 1)[1].split("```", 1)[0]

    async with TemporaryDirectory(prefix="snekql-preview-typing-") as directory:
        caller = Path(directory) / "preview.py"
        await caller.write_text(
            quick_start
            + "\nfrom typing import assert_type\n"
            + "\nasync def preview(db: sqlite.Database) -> None:\n"
            + indent(preview, "    ")
            + "\n    assert_type(users, list[User[sqlite.Row]])\n"
        )
        checked = await run_process(
            [sys.executable, "-m", "ty", "check", str(caller)], check=False
        )

    assert_eq(
        checked.returncode, 0, msg=checked.stdout.decode() + checked.stderr.decode()
    )
