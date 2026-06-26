"""Docs CLI tests."""

from __future__ import annotations

import subprocess
import sys

from snektest import assert_eq, assert_in, test


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
