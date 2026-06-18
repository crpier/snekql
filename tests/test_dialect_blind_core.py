"""Dialect-blindness invariant for the shared core (ADR 0004).

No core module may import a Backend Namespace (`snekql.sqlite`, `snekql.mariadb`).
The concrete Dialect / Backend Runtime Adapter is injected at the edge, never
imported by the core, so backends stay independently evolvable and the package
can later split into separate distributions.
"""

from __future__ import annotations

from pathlib import Path

from snektest import test

import snekql

_BACKEND_NAMESPACES = ("snekql.sqlite", "snekql.mariadb")
_NAMED_CORE_MODULES = ("runtime.py", "query.py", "model.py", "storage.py")


def _core_module_paths() -> list[Path]:
    """Resolve the core modules the dialect-blindness invariant covers."""

    package_dir = Path(snekql.__file__).parent
    underscore_modules = sorted(package_dir.glob("_*.py"))
    named_modules = [package_dir / name for name in _NAMED_CORE_MODULES]
    return [*underscore_modules, *named_modules]


@test(mark="fast")
def core_modules_do_not_import_a_backend_namespace() -> None:
    """Every core module is free of Backend Namespace references."""

    offenders: dict[str, list[str]] = {}
    for module_path in _core_module_paths():
        source = module_path.read_text(encoding="utf-8")
        hits = [namespace for namespace in _BACKEND_NAMESPACES if namespace in source]
        if hits:
            offenders[module_path.name] = hits

    assert not offenders, (
        f"core modules must not reference a Backend Namespace: {offenders}"
    )
