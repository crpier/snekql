"""Copy actual package declarations for static-only research; never import the copy."""

import ast
from pathlib import Path
from shutil import copytree, ignore_patterns

ROOT = Path(__file__).resolve().parents[2]
TEXT_DECLARATION_COUNT = 8


def build_overlay(destination: Path, *, modified: bool = True) -> None:
    """Create a disposable package and matching all-error checker policy."""
    copytree(
        ROOT / "snekql",
        destination / "snekql",
        ignore=ignore_patterns("__pycache__", "*.pyc"),
    )
    (destination / "pyproject.toml").write_text(
        '[tool.ty.rules]\nall = "error"\nmissing-override-decorator = "ignore"\n'
    )
    if not modified:
        return
    for relative in ("storage.py", "mariadb/storage.py"):
        path = destination / "snekql" / relative
        source = path.read_text()
        nodes = [
            node
            for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name == "Text"
        ]
        if len(nodes) != TEXT_DECLARATION_COUNT:
            msg = f"Expected seven Text overloads and an implementation in {relative}"
            raise ValueError(msg)
        lines = source.splitlines(keepends=True)
        for node in reversed(nodes):
            # Only signatures change. The copied runtime still does not implement
            # server_default; this copy must never be imported or executed.
            is_implementation = not node.decorator_list
            marker = " | EllipsisType" if is_implementation else ""
            lines.insert(
                node.lineno + 1,
                "    server_default: str | int | None | type[CurrentTimestamp]"
                f"{marker} = ...,\n",
            )
        path.write_text("".join(lines))
