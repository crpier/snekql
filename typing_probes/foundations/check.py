"""Run isolated caller-side typing experiments, never execute their source."""

import os
import sys
from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import version
from json import dumps, loads
from pathlib import Path
from platform import python_implementation

from anyio import Path as AsyncPath
from anyio import TemporaryDirectory, fail_after, run, run_process, to_thread
from pydantic import BaseModel, TypeAdapter


class Position(BaseModel):
    """One-based position in ty's GitLab diagnostic format."""

    line: int


class Positions(BaseModel):
    begin: Position


class Location(BaseModel):
    path: str
    positions: Positions


class Diagnostic(BaseModel):
    check_name: str
    description: str
    location: Location


@dataclass(frozen=True)
class Case:
    """A valid control, optionally followed by one independently checked mistake."""

    name: str
    template: str
    valid: str
    invalid: str = ""
    rejects: bool = True


async def check_case(case: Case) -> dict[str, object]:
    """Require a clean control and only the intended negative-line diagnostics."""
    root = Path(__file__).parents[2]
    header = await AsyncPath(
        root / "typing_probes/foundations" / case.template
    ).read_text()
    source = (
        header
        + "\n\ndef probe() -> None:\n"
        + "\n".join("    " + line for line in case.valid.splitlines())
        + "\n"
    )
    environment = dict(os.environ)
    environment.pop("TY_CONFIG_FILE", None)
    observations: list[dict[str, object]] = []
    # The host's /tmp has a per-user quota. Keep temporary inputs in the checkout.
    async with TemporaryDirectory(dir=str(root / ".git")) as directory:
        probe_path = AsyncPath(directory) / "probe.py"
        for negative in (False, True) if case.invalid else (False,):
            rendered = source + ("    " + case.invalid + "\n" if negative else "")
            await probe_path.write_text(rendered)
            arguments = [
                "ty",
                "check",
                str(probe_path),
                "--project",
                str(root),
                "--extra-search-path",
                str(root),
                "--python",
                sys.executable,
                "--python-version",
                "3.14",
                "--output-format",
                "gitlab",
            ]
            with fail_after(30):
                checked = await run_process(arguments, env=environment, check=False)
            diagnostics = TypeAdapter(list[Diagnostic]).validate_json(checked.stdout)
            expected_line = len(rendered.splitlines())
            if negative and case.rejects:
                conforms = (
                    checked.returncode == 1
                    and bool(diagnostics)
                    and all(
                        diagnostic.location.positions.begin.line == expected_line
                        and root / diagnostic.location.path == Path(str(probe_path))
                        and diagnostic.check_name
                        not in {"unresolved-import", "unresolved-reference"}
                        for diagnostic in diagnostics
                    )
                )
            else:
                conforms = checked.returncode == 0 and not diagnostics
            observations.append(
                {
                    "negative": negative,
                    "conforms": conforms,
                    "source_sha256": sha256(rendered.encode()).hexdigest(),
                    "diagnostics": [
                        diagnostic.model_dump() for diagnostic in diagnostics
                    ],
                    "exit_code": checked.returncode,
                }
            )
    return {
        "name": case.name,
        "expected_rejection": case.rejects if case.invalid else None,
        "conforms": all(observation["conforms"] for observation in observations),
        "observations": observations,
    }


async def main() -> None:
    """Write a reproducible report including counterexamples we expect to pass."""
    directory = AsyncPath(__file__).parent
    definitions = loads(await (directory / "cases.json").read_text())
    results = [await check_case(Case(**definition)) for definition in definitions]
    sources = {}
    async for path in directory.iterdir():
        if path.suffix in {".py", ".pyi", ".txt"} or path.name == "cases.json":
            sources[path.name] = sha256(await path.read_bytes()).hexdigest()
    revision = await run_process(["git", "rev-parse", "HEAD"], check=False)
    report = {
        "python": sys.version,
        "implementation": python_implementation(),
        "ty": await to_thread.run_sync(version, "ty"),
        "python_target": "3.14",
        "base_revision": revision.stdout.decode().strip(),
        "source_sha256": dict(sorted(sources.items())),
        "results": results,
    }
    await (directory / "results.json").write_text(dumps(report, indent=2) + "\n")
    for result in results:
        print(f"{'PASS' if result['conforms'] else 'FAIL'} {result['name']}")
    sys.exit(0 if all(result["conforms"] for result in results) else 1)


if __name__ == "__main__":
    run(main)
