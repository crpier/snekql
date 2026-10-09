"""Run snektest under forced lazy imports, excluding incompatible test-tool internals.

Usage: `uv run python -X lazy_imports=all scripts/run_lazy_tests.py tests`.
The filter works around Hypothesis registration and an OpenTelemetry SDK metrics
import cycle. No snekql, test, stdlib, or OpenTelemetry API imports are excluded.
"""

lazy import sys
lazy from pathlib import Path
lazy from runpy import run_module


def _allow_lazy_import(
    importer: str | None, name: str, fromlist: tuple[str, ...] | None
) -> bool:
    """Preserve test-tool initialization without exempting library imports."""
    del name, fromlist
    if importer is None:
        return True
    return not any(
        importer == package or importer.startswith(f"{package}.")
        for package in ("hypothesis", "opentelemetry.sdk")
    )


if __name__ == "__main__":
    if sys.get_lazy_imports() != "all":
        message = "run with python -X lazy_imports=all"
        raise SystemExit(message)
    sys.set_lazy_imports_filter(_allow_lazy_import)
    # Running a script puts scripts/, not the source checkout, on sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    run_module("snektest", run_name="__main__")
