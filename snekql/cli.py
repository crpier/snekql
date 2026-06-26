"""Command line access to bundled snekql documentation."""

from __future__ import annotations

import sys
from argparse import ArgumentParser

from snekql.agent_docs import get_agent_docs, get_example_source, get_examples_listing
from snekql.errors import SnekqlError

ARGS_ERROR = 2
EXAMPLE_COMMAND_PARTS = 2

HELP_TEXT = """Usage: snekql [OPTIONS]
       snekql examples
       snekql example NAME

Print bundled snekql documentation.

Options:
  -h, --help        Show this help message
  --agent-docs      Print AI-agent usage guide
  --llms            Alias for --agent-docs
  --examples        List bundled examples
  --example NAME    Print a bundled example
"""


def _build_parser() -> ArgumentParser:
    """Define the documentation CLI surface."""

    parser = ArgumentParser(add_help=False, prog="snekql")
    _ = parser.add_argument("-h", "--help", action="store_true")
    _ = parser.add_argument("--agent-docs", "--llms", action="store_true")
    _ = parser.add_argument("--examples", action="store_true")
    _ = parser.add_argument("--example")
    _ = parser.add_argument("command", nargs="*")
    return parser


def _print_example(example_name: str) -> int:
    """Print one bundled example by name."""

    try:
        print(get_example_source(example_name), end="")
    except SnekqlError as error:
        print(str(error), file=sys.stderr)
        return ARGS_ERROR
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the snekql documentation CLI."""

    namespace = _build_parser().parse_args(argv)
    example_name = namespace.example
    if namespace.command[:1] == ["example"]:
        if len(namespace.command) < EXAMPLE_COMMAND_PARTS:
            print("Missing example name", file=sys.stderr)
            return ARGS_ERROR
        example_name = namespace.command[1]

    if namespace.help:
        print(HELP_TEXT, end="")
    elif namespace.agent_docs:
        print(get_agent_docs(), end="")
    elif namespace.examples or namespace.command == ["examples"]:
        print(get_examples_listing(), end="")
    elif example_name is not None:
        return _print_example(example_name)
    elif namespace.command:
        print(f"Unknown command: {namespace.command[0]}", file=sys.stderr)
        return ARGS_ERROR
    else:
        print(HELP_TEXT, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
