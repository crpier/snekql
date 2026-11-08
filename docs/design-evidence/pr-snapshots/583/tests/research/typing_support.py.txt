"""Exact paired checker runner for #473; never execute rendered callers."""

import sys
from json import loads

from anyio import Path, TemporaryDirectory, fail_after, run_process
from snektest import assert_eq, assert_true


async def assert_paired_typing(
    source: str,
    *,
    modules: dict[str, str] | None = None,
    positive_source: str | None = None,
) -> None:
    """Require clean controls and exact diagnostics; comma-separated rules share a line."""
    async with TemporaryDirectory(prefix="snekql-nullability-473-") as directory:
        positive = Path(directory) / "positive.py"
        negative = Path(directory) / "negative.py"
        module_paths: list[str] = []
        for name, module_source in (modules or {}).items():
            path = Path(directory) / f"{name}.py"
            await path.write_text(module_source)
            module_paths.append(str(path))
        await positive.write_text(
            positive_source
            if positive_source is not None
            else "\n".join(
                line for line in source.splitlines() if "# error:" not in line
            )
        )
        await negative.write_text(source)
        expected_errors = [
            (index, rule.strip())
            for index, line in enumerate(source.splitlines(), 1)
            if "# error: " in line
            for rule in line.split("# error: ")[1].split(",")
        ]
        assert_true(bool(expected_errors))
        for path, expected in ((positive, []), (negative, expected_errors)):
            with fail_after(30):
                completed = await run_process(
                    [
                        sys.executable,
                        "-m",
                        "ty",
                        "check",
                        "--output-format",
                        "gitlab",
                        "--extra-search-path",
                        ".",
                        "--extra-search-path",
                        directory,
                        str(path),
                        *module_paths,
                    ],
                    check=False,
                )
            diagnostics = loads(completed.stdout)
            for item in diagnostics:
                assert_eq(item["location"]["path"], str(path))
            observed = [
                (item["location"]["positions"]["begin"]["line"], item["check_name"])
                for item in diagnostics
            ]
            assert_eq(observed, expected, msg=completed.stdout.decode())
            assert_eq(completed.returncode, int(bool(expected)))
