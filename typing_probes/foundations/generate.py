"""Generate a throwaway typed facade from dataclass field facts.

Only builtin scalar annotations and unions are supported in this experiment.
This is a real generator, not a manually maintained duplicate model definition.
The output is a static contract, not an implemented query runtime.
"""

from dataclasses import MISSING, fields, is_dataclass
from types import UnionType
from typing import get_args, get_origin, get_type_hints

from anyio import Path, run, run_process

from typing_probes.foundations.schema import Account


class GenerationError(Exception):
    """The prototype cannot emit a requested schema annotation."""


def _annotation_name(annotation: object) -> str:
    if annotation is type(None):
        return "None"
    if get_origin(annotation) is UnionType:
        return " | ".join(
            _annotation_name(argument) for argument in get_args(annotation)
        )
    if annotation in (int, str, float, bool, bytes) and isinstance(annotation, type):
        return annotation.__name__
    message = f"Unsupported prototype annotation: {annotation}"
    raise GenerationError(message)


def render_facade(row_type: type[object]) -> str:
    """Emit columns and an insert signature, preserving required/defaulted fields."""
    if not is_dataclass(row_type):
        message = "Expected a dataclass row type"
        raise GenerationError(message)
    annotations = get_type_hints(row_type)
    column_lines: list[str] = []
    arguments: list[str] = []
    for field in fields(row_type):
        logical_type = _annotation_name(annotations[field.name])
        column_lines.append(
            f"    {field.name}: Column[{row_type.__name__}, {logical_type}]"
        )
        optional = (
            field.metadata.get("generated")
            or field.default is not MISSING
            or field.default_factory is not MISSING
        )
        arguments.append(
            f"{field.name}: {logical_type}" + (" = ..." if optional else "")
        )
    row_name = row_type.__name__
    return "\n".join(
        [
            '"""Throwaway generated typing facade. Regenerate with foundations.generate."""',
            "",
            "# Preserve schema field names and explanatory research docstrings.",
            "# ruff: noqa: A002, PYI021",
            "",
            "from typing_probes.foundations.core import Column, Deleting, Query, Updating, Write",
            f"from {row_type.__module__} import {row_name}",
            "",
            f"class {row_name}Table:",
            *column_lines,
            f"    def select(self) -> Query[{row_name}, {row_name}]: ...",
            f"    def insert(self, *, {', '.join(arguments)}) -> Write[{row_name}]: ...",
            f"    def update(self) -> Updating[{row_name}]: ...",
            f"    def delete(self) -> Deleting[{row_name}]: ...",
            "",
            f"accounts: {row_name}Table",
            "",
        ]
    )


async def main() -> None:
    """Regenerate the example's checked-in typing facade."""
    formatted = await run_process(
        ["ruff", "format", "--stdin-filename", "generated.pyi", "-"],
        input=render_facade(Account).encode(),
    )
    await Path(__file__).with_name("generated.pyi").write_bytes(formatted.stdout)


if __name__ == "__main__":
    run(main)
