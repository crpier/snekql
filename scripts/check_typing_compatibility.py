"""Check paired consumer typing examples without executing database operations."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from hashlib import sha256
from importlib.metadata import version
from json import dumps
from pathlib import Path
from platform import platform

from anyio import Path as AsyncPath
from anyio import TemporaryDirectory, fail_after, run, run_process, to_thread
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

_CASES = (
    "lifecycle",
    "row-constructor",
    "bulk-destination",
    "bulk-row-state",
    "bulk-backend",
    "bulk-source",
    "insert-sequence",
    "insert-empty",
    "insert-tuple",
    "read-scope",
    "ready-write",
    "ready-scope",
    "closed-assignment",
    "closed-optional",
    "ready-backend",
    "pending-input",
    "read-constructor",
    "readonly-scalar",
    "scalar-outer-scope",
    "exists-outer-scope",
    "nullable-expression",
    "write-validation",
    "returning-domain",
    "exists-family",
    "nested-exists-family",
    "nested-scalar-family",
    "nested-membership-family",
    "nested-projection-family",
    "nested-fk-family",
    "nested-helper-family",
    "not-exists-family",
    "scalar-family",
    "compare-eq",
    "compare-ne",
    "compare-gt",
    "compare-gte",
    "compare-lt",
    "compare-lte",
    "frozen-row",
    "frozen-pending",
    "frozen-generated",
    "compare-alias",
    "source-select",
    "source-row",
    "source-pretender",
    "source-join",
    "source-left-join",
    "source-update",
    "source-delete",
    "source-alias",
    "readiness",
    "backend-identity",
    "positional-width",
    "named-result",
    "joins",
    "raw-contract",
    "fk-defaults",
)
"""Consumer contracts with paired positive and negative source templates."""


class ProbeError(Exception):
    """A checker could not produce a usable conformance assessment."""


class _Position(BaseModel):
    line: int


class _Positions(BaseModel):
    begin: _Position


class _Location(BaseModel):
    path: str
    positions: _Positions


class _TyDiagnostic(BaseModel):
    check_name: str
    description: str
    location: _Location
    severity: str


class _Range(BaseModel):
    start: _Position


class _PyrightDiagnostic(BaseModel):
    file: str
    message: str
    rule: str = "unknown"
    severity: str
    span: _Range = Field(alias="range")


class _PyrightReport(BaseModel):
    diagnostics: list[_PyrightDiagnostic] = Field(alias="generalDiagnostics")


class _MypyDiagnostic(BaseModel):
    code: str | None = None
    file: str
    line: int
    message: str
    severity: str


class _Diagnostic(BaseModel):
    file: str
    line: int
    message: str
    rule: str


class _Source(BaseModel):
    backend: str
    expected_line: int
    name: str
    negative_path: str
    negative_sha256: str
    positive_path: str
    positive_sha256: str


class _Case(BaseModel):
    backend: str
    conforms: bool
    expected_line: int
    name: str
    negative_errors: list[_Diagnostic]
    negative_sha256: str
    positive_errors: list[_Diagnostic]
    positive_sha256: str


class _Environment(BaseModel):
    packages: dict[str, str]
    platform: str
    python: str
    source_commit: str | None = None
    source_dirty: bool | None = None


class _Report(BaseModel):
    cases: list[_Case]
    checker: str
    checker_version: str
    command: list[str]
    conforms: bool
    environment: _Environment
    recorded_at: str
    schema_version: int = 1
    unmapped_errors: list[_Diagnostic]


def _environment_versions() -> _Environment:
    """Distribution and host lookups run off the event loop."""
    return _Environment(
        packages={
            name: version(name) for name in ("snekql", "pydantic", "anyio", "ty")
        },
        platform=platform(),
        python=sys.version,
    )


async def _environment(root: AsyncPath) -> _Environment:
    """Missing checkout metadata remains unknown, never a fabricated clean state."""
    environment = await to_thread.run_sync(_environment_versions)
    try:
        revision = await run_process(
            ["git", "rev-parse", "HEAD"], cwd=str(root), check=False
        )
        dirty = await run_process(
            ["git", "status", "--porcelain"], cwd=str(root), check=False
        )
    except OSError:
        return environment
    if revision.returncode == 0:
        environment.source_commit = revision.stdout.decode().strip()
    if dirty.returncode == 0:
        environment.source_dirty = bool(dirty.stdout)
    return environment


def _parse_diagnostics(checker: str, output: bytes) -> list[_Diagnostic]:
    """Normalize real checker protocols without counting informational notes."""
    if checker == "ty":
        return [
            _Diagnostic(
                file=str(Path(d.location.path)),
                line=d.location.positions.begin.line,
                message=d.description,
                rule=d.check_name,
            )
            for d in TypeAdapter(list[_TyDiagnostic]).validate_json(output)
            if d.severity in ("major", "critical", "blocker")
        ]
    if checker == "pyright":
        return [
            _Diagnostic(
                file=str(Path(d.file)),
                line=d.span.start.line + 1,
                message=d.message,
                rule=d.rule,
            )
            for d in _PyrightReport.model_validate_json(output).diagnostics
            if d.severity == "error"
        ]
    diagnostics: list[_Diagnostic] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        diagnostic = _MypyDiagnostic.model_validate_json(line)
        if diagnostic.severity == "error":
            diagnostics.append(
                _Diagnostic(
                    file=str(Path(diagnostic.file)),
                    line=diagnostic.line,
                    message=diagnostic.message,
                    rule=diagnostic.code or "unknown",
                )
            )
    return diagnostics


async def _invoke_checker(
    checker: str, root: AsyncPath, directory: str, paths: list[str]
) -> tuple[str, list[str], list[_Diagnostic]]:
    """Pin secondary tools and point every checker at the same consumer environment."""
    environment = dict(os.environ)
    if checker == "ty":
        executable = str(
            Path(sys.executable).with_name("ty.exe" if os.name == "nt" else "ty")
        )
        prefix = [executable]
        config = AsyncPath(directory) / "ty.toml"
        await config.write_text(
            '[rules]\nall = "error"\nmissing-override-decorator = "ignore"\n'
        )
        arguments = [
            "check",
            "--config-file",
            str(config),
            "--python",
            sys.executable,
            "--python-version",
            "3.14",
            "--extra-search-path",
            str(root),
            "--output-format",
            "gitlab",
            *paths,
        ]
    elif checker == "pyright":
        prefix = ["uv", "tool", "run", "--from", "pyright==1.1.414", "pyright"]
        config = AsyncPath(directory) / "pyrightconfig.json"
        await config.write_text(
            dumps(
                {
                    "typeCheckingMode": "strict",
                    "pythonVersion": "3.14",
                    "include": paths,
                    "extraPaths": [str(root)],
                }
            )
        )
        arguments = [
            "--pythonpath",
            sys.executable,
            "--project",
            str(config),
            "--outputjson",
        ]
    else:
        prefix = ["uv", "tool", "run", "--from", "mypy==2.3.1", "mypy"]
        config = AsyncPath(directory) / "mypy.ini"
        await config.write_text("[mypy]\n")
        environment["MYPYPATH"] = str(root)
        arguments = [
            "--strict",
            "--python-version",
            "3.14",
            "--python-executable",
            sys.executable,
            "--config-file",
            str(config),
            "--no-incremental",
            "--cache-dir",
            directory,
            "--output",
            "json",
            *paths,
        ]
    version = await run_process([*prefix, "--version"], check=False, env=environment)
    if version.returncode != 0:
        message = f"{checker} version probe failed"
        raise ProbeError(message)
    command = [*prefix, *arguments]
    completed = await run_process(command, check=False, env=environment)
    if completed.returncode not in (0, 1):
        message = f"{checker} invocation failed with status {completed.returncode}"
        raise ProbeError(message)
    diagnostics = _parse_diagnostics(checker, completed.stdout)
    if (completed.returncode == 1) != bool(diagnostics):
        message = f"{checker} exit status disagrees with its error diagnostics"
        raise ProbeError(message)
    return version.stdout.decode().strip(), command, diagnostics


async def _write_sources(
    root: AsyncPath, directory: str, backend: str, selection: str
) -> list[_Source]:
    """Materialize paired examples; their filenames identify diagnostic ownership."""
    sources: list[_Source] = []
    for name in _CASES if selection == "all" else (selection,):
        positive_template = await (
            root / f"typing_probes/{name}.positive.py.txt"
        ).read_text()
        negative_template = await (
            root / f"typing_probes/{name}.negative.py.txt"
        ).read_text()
        for family in ("sqlite", "mariadb") if backend == "all" else (backend,):
            positive = positive_template.replace("__BACKEND__", family).replace(
                "__OTHER_BACKEND__", "mariadb" if family == "sqlite" else "sqlite"
            )
            negative = positive + negative_template
            expected_lines = [
                index
                for index, line in enumerate(negative.splitlines(), start=1)
                if "# expect-error" in line
            ]
            if len(expected_lines) != 1:
                message = "each negative probe must mark exactly one expected error"
                raise ProbeError(message)
            positive_path = str(Path(directory) / f"{family}_{name}_positive.py")
            negative_path = str(Path(directory) / f"{family}_{name}_negative.py")
            await AsyncPath(positive_path).write_text(
                positive, encoding="utf-8", newline="\n"
            )
            await AsyncPath(negative_path).write_text(
                negative, encoding="utf-8", newline="\n"
            )
            sources.append(
                _Source(
                    backend=family,
                    expected_line=expected_lines[0],
                    name=name,
                    negative_path=negative_path,
                    negative_sha256=sha256(negative.encode()).hexdigest(),
                    positive_path=positive_path,
                    positive_sha256=sha256(positive.encode()).hexdigest(),
                )
            )
    return sources


async def _assess(backend: str, checker: str, case_name: str) -> _Report:
    """A negative diagnostic is evidence only when its positive control is clean."""
    root = (await AsyncPath(__file__).resolve()).parent.parent
    async with TemporaryDirectory(prefix="snekql-typing-") as directory:
        sources = await _write_sources(root, directory, backend, case_name)
        paths = [
            path
            for source in sources
            for path in (source.positive_path, source.negative_path)
        ]
        version, command, diagnostics = await _invoke_checker(
            checker, root, directory, paths
        )
        observations: list[_Case] = []
        for source in sources:
            positive_errors = [d for d in diagnostics if d.file == source.positive_path]
            negative_errors = [d for d in diagnostics if d.file == source.negative_path]
            observations.append(
                _Case(
                    backend=source.backend,
                    conforms=not positive_errors
                    and bool(negative_errors)
                    and all(
                        error.line == source.expected_line for error in negative_errors
                    ),
                    expected_line=source.expected_line,
                    name=source.name,
                    negative_errors=negative_errors,
                    negative_sha256=source.negative_sha256,
                    positive_errors=positive_errors,
                    positive_sha256=source.positive_sha256,
                )
            )
        unmapped = [d for d in diagnostics if d.file not in paths]
        return _Report(
            cases=observations,
            checker=checker,
            checker_version=version,
            command=command,
            conforms=all(case.conforms for case in observations) and not unmapped,
            environment=await _environment(root),
            recorded_at=datetime.now(UTC).isoformat(),
            unmapped_errors=unmapped,
        )


async def _run_cli(backend: str, checker: str, case_name: str) -> _Report:
    """Bound the entire checker assessment, including tool startup."""
    with fail_after(90):
        return await _assess(backend, checker, case_name)


def main() -> int:
    """Emit one complete report, or a separate infrastructure error."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checker", choices=("ty", "pyright", "mypy"), default="ty")
    parser.add_argument(
        "--backend", choices=("all", "sqlite", "mariadb"), default="all"
    )
    parser.add_argument("--case", choices=("all", *_CASES), default="all")
    options = parser.parse_args()
    try:
        report = run(_run_cli, options.backend, options.checker, options.case)
    except (OSError, TimeoutError, ValidationError, ProbeError) as error:
        print(f"typing assessment unavailable: {error}", file=sys.stderr)
        return 2
    print(dumps(report.model_dump()))
    return 0 if report.conforms else 1


if __name__ == "__main__":
    raise SystemExit(main())
