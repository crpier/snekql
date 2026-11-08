"""Copy real sources and apply the narrow, checker-only #606 experiment.

This is not a runtime implementation or proposed public API. The copied package
is checked, never imported by the research suite. Missing source anchors fail.
"""

import re
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_FACTORY_ARGUMENTS = 6


def _once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        message = f"Expected exactly one source anchor: {old!r}"
        raise ValueError(message)
    return source.replace(old, new, 1)


def _arguments(text: str) -> list[str]:
    depth = 0
    start = 0
    parts: list[str] = []
    for i, character in enumerate(text):
        if character in "[({":
            depth += 1
        elif character in "])}":
            depth -= 1
        elif character == "," and depth == 0:
            parts.append(text[start:i].strip())
            start = i + 1
    parts.append(text[start:].strip())
    return [part for part in parts if part]


def _generic(source: str, name: str, change: Callable[[list[str]], list[str]]) -> str:
    """Rewrite balanced applications, including multiline descriptor annotations."""
    matches = list(re.finditer(rf"\b{re.escape(name)}\[", source))
    for match in reversed(matches):
        begin = match.end()
        end = begin
        depth = 1
        while depth:
            character = source[end]
            depth += (character == "[") - (character == "]")
            end += 1
        old = _arguments(source[begin : end - 1])
        new = change(old)
        if new != old:
            source = "".join((source[:begin], ", ".join(new), source[end - 1 :]))
    return source


def _imports(source: str) -> str:
    return (
        source
        + "\n\nfrom typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from ty_extensions import Intersection\n    from snekql._capability_probe import _StorageCapability\n"
    )


def _cap(args: list[str], count: int) -> list[str]:
    return [*args, "CapabilityT"] if len(args) == count else args


def _receiver(source: str, name: str, receiver: str) -> str:
    old = f"def {name}(self"
    return _once(
        source,
        old,
        f'def {name}(self: Intersection[{receiver}, _StorageCapability[Literal["numeric"]]]',
    )


def build(destination: Path, *, derived: bool = False) -> None:
    """Build the direct slice, optionally carrying its witness through CTEs."""
    package = destination / "snekql"
    shutil.copytree(
        ROOT / "snekql", package, ignore=shutil.ignore_patterns("__pycache__")
    )
    (package / "_capability_probe.py").write_text(
        "from typing import Protocol\n\n"
        "class _StorageCapability[CapabilityT](Protocol):\n"
        "    def __storage_capability__(self) -> CapabilityT: ...\n"
    )
    path = package / "storage.py"
    source = path.read_text()
    start = source.index("class Attr[")
    end = source.index("class FKAttr[")
    attr = source[start:end]
    attr = _once(
        attr, "    FamilyT = Any,\n", "    FamilyT = Any,\n    CapabilityT = object,\n"
    )
    attr = _generic(attr, "Attr", lambda args: _cap(args, 8))
    # Keep logical values, comparison domains, owners and family independent.
    if derived:
        attr = _generic(attr, "_NullExtendedLabel", lambda args: _cap(args, 4))
    attr = _once(
        attr,
        "    def label(\n",
        "    def __storage_capability__(self) -> CapabilityT:\n"
        "        raise NotImplementedError\n\n    def label(\n",
    )
    attr_receiver = "Attr[WriteOwnerT, LoadedOwnerT, OwnerT, WriteT, ReadValueT, SetValueT, CompareT, FamilyT, CapabilityT]"
    for method in ("sum", "avg", "min", "max", "asc", "desc"):
        attr = _receiver(attr, method, attr_receiver)
    source = source[:start] + attr + source[end:]
    start = source.index("class FKAttr[")
    end = source.index("class _DeferredFKAttr", start)
    fk = source[start:end]
    fk = _once(
        fk, "    FamilyT = Any,\n", "    FamilyT = Any,\n    CapabilityT = object,\n"
    )
    fk = _generic(fk, "Attr", lambda args: _cap(args, 8))
    fk = _generic(fk, "FKAttr", lambda args: _cap(args, 9))
    source = source[:start] + fk + source[end:]
    # Constructor contracts, not Any or caller-chosen capability inference.
    source = _constructor(source, "Text", "Blob", "text", "sqlite")
    path.write_text(_imports(source))

    path = package / "expressions.py"
    source = path.read_text()
    comparable = "Comparable[OwnerT, ValueT, ColumnValueT, FamilyT]"
    for method in ("gt", "gte", "lt", "lte", "between"):
        source = _receiver(source, method, comparable)
    path.write_text(_imports(source))

    for backend in ("sqlite", "mariadb"):
        path = package / backend / "model.py"
        source = path.read_text().replace(
            "type Col[T] = Attr[", "type Col[T, CapabilityT = object] = Attr["
        )
        # Both the nested Model.Col and namespace-level Col aliases.
        source = _generic(
            source,
            "Attr",
            lambda args: (
                _cap(args, 8)
                if args[0] == "Table[Pending]" and args[3:5] == ["T", "T"]
                else args
            ),
        )
        path.write_text(source)
    path = package / "mariadb" / "storage.py"
    source = _constructor(path.read_text(), "Decimal", "Json", "numeric", "mariadb")
    source = _constructor(source, "Text", "LongText", "text", "mariadb")
    path.write_text(source)
    if derived:
        _derived(package)


def _constructor(source: str, name: str, following: str, cap: str, family: str) -> str:
    start = source.index(f"def {name}[")
    end = source.index(f"def {following}[", start)
    section = source[start:end]
    section = _generic(
        section,
        "FKAttr",
        lambda args: (
            [*args, args[3], "Any", f'Literal["{family}"]', f'Literal["{cap}"]']
            if len(args) == _FACTORY_ARGUMENTS
            else args
        ),
    )
    return source[:start] + section + source[end:]


def _derived(package: Path) -> None:
    path = package / "_output_label.py"
    source = path.read_text()
    source = source.replace(
        "CompareT, FamilyT = Any]", "CompareT, FamilyT = Any, CapabilityT = object]"
    )
    source = _generic(source, "_OutputLabel", lambda args: _cap(args, 4))
    source = _once(
        source,
        "    def __value_type__(self) -> T:\n",
        "    def __storage_capability__(self) -> CapabilityT:\n"
        "        raise NotImplementedError\n\n    def __value_type__(self) -> T:\n",
    )
    path.write_text(source)
    path = package / "_cte.py"
    source = path.read_text()
    source = source.replace(
        "CompareT, FamilyT = Any]", "CompareT, FamilyT = Any, CapabilityT = object]"
    )
    source = _generic(source, "_LabelContract", lambda args: _cap(args, 4))
    source = _generic(source, "_SensitiveLabelContract", lambda args: _cap(args, 4))
    source = _once(
        source,
        "    def __value_type__(self) -> T: ...\n",
        "    def __storage_capability__(self) -> CapabilityT: ...\n\n"
        "    def __value_type__(self) -> T: ...\n",
    )
    source = source.replace(
        "def column[T, CompareT]", "def column[T, CompareT, CapabilityT]"
    )
    source = source.replace(
        "def column[TokenOwnerT, T, CompareT]",
        "def column[TokenOwnerT, T, CompareT, CapabilityT]",
    )
    source = _generic(source, "_CteOutput", lambda args: _cap(args, 4))
    source = _generic(source, "_NullExtendedLabel", lambda args: _cap(args, 4))
    source = _once(
        source,
        "    def __column_value_type__(self) -> T:\n",
        "    def __storage_capability__(self) -> CapabilityT:\n"
        "        raise NotImplementedError\n\n    def __column_value_type__(self) -> T:\n",
    )
    receiver = "_CteOutput[OwnerT, T, CompareT, FamilyT, CapabilityT]"
    for method in ("sum", "avg", "min", "max", "asc", "desc"):
        source = _receiver(source, method, receiver)
    source = source.replace(
        "from typing import Any, ClassVar, Protocol, cast, overload",
        "from typing import Any, ClassVar, Literal, Protocol, cast, overload",
    )
    path.write_text(_imports(source))


if __name__ == "__main__":
    build(Path(sys.argv[1]), derived="--derived" in sys.argv[2:])
