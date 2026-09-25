"""Independent ty callers: clean controls, exact inferred types, located diagnostics."""

import sys
from ast import AsyncFunctionDef, AsyncWith, Return, parse, unparse
from hashlib import sha256
from importlib.metadata import version
from json import dumps, loads
from textwrap import indent
from typing import Any

from anyio import Path, TemporaryDirectory, fail_after, run, run_process, to_thread


async def _check_application_callers(
    directory: Path, cases: list[dict[str, Any]]
) -> None:
    # Stored callers must still match the actual application expressions.
    for style in ("application",):
        module = parse(await (directory / f"{style}.py").read_text())
        for function in module.body:
            if not isinstance(function, AsyncFunctionDef):
                continue
            lines = []
            for node in function.body:
                if (
                    isinstance(node, Return)
                    and node.value is not None
                    and function.returns is not None
                ):
                    lines.append(
                        "assert_type("
                        + unparse(node.value)
                        + ","
                        + unparse(function.returns)
                        + ")"
                    )
                elif isinstance(node, AsyncWith):
                    row_type = "UserRow"
                    lines.append(
                        unparse(node).replace(
                            "yield batch", f"assert_type(batch,list[{row_type}])"
                        )
                    )
                else:
                    lines.append(unparse(node))
            stored = next(
                case for case in cases if case["name"] == style + "-" + function.name
            )
            if stored["challenge"] != "\n".join(lines):
                message = f"Stale application caller: {style}.{function.name}"
                raise SystemExit(message)


async def main() -> None:
    directory = Path(__file__).parent
    root = directory.parent.parent
    temporary_root = root / ".git/dual-descriptors"
    await temporary_root.mkdir(exist_ok=True)
    header = await (directory / "header.py.txt").read_text()
    cases = loads(await (directory / "cases.json").read_text())
    await _check_application_callers(directory, cases)
    observations: list[dict[str, object]] = []
    async with TemporaryDirectory(dir=str(temporary_root)) as temporary:
        source = Path(temporary) / "caller.py"
        for case in cases:
            phases: list[dict[str, object]] = []
            diagnostic_codes: list[str] = []
            for challenge in (False, True):
                text = (
                    case.get("header", header) + indent(case["control"], "    ") + "\n"
                )
                start = text.count("\n") + 1
                if challenge:
                    text += indent(case["challenge"], "    ") + "\n"
                await source.write_text(text)
                with fail_after(15):
                    process = await run_process(
                        [
                            "uv",
                            "run",
                            "ty",
                            "check",
                            str(source),
                            "--python-version",
                            "3.14",
                            "--output-format",
                            "gitlab",
                        ],
                        cwd=str(root),
                        check=False,
                    )
                diagnostics = loads(process.stdout or b"[]")
                diagnostic_codes.extend(item["check_name"] for item in diagnostics)
                rejects = challenge and case["rejects"]
                matched = (
                    (
                        process.returncode == 1
                        and bool(diagnostics)
                        and all(
                            start
                            <= item["location"]["positions"]["begin"]["line"]
                            <= text.count("\n")
                            and item["location"]["path"]
                            in {str(source), str(source.relative_to(root))}
                            and item["check_name"]
                            not in {
                                "unresolved-import",
                                "unresolved-reference",
                                "invalid-syntax",
                            }
                            for item in diagnostics
                        )
                    )
                    if rejects
                    else process.returncode == 0 and not diagnostics
                )
                phases.append(
                    {
                        "challenge": challenge,
                        "matched": matched,
                        "challenge_start": start,
                        "exit_code": process.returncode,
                        "stderr": process.stderr.decode(),
                        "diagnostics": [
                            {
                                "code": item["check_name"],
                                "message": item["description"],
                                "location": item["location"],
                            }
                            for item in diagnostics
                        ],
                    }
                )
                if not matched:
                    print(
                        case["name"],
                        "challenge" if challenge else "control",
                        process.stdout.decode(),
                        process.stderr.decode(),
                    )
            observations.append(
                {
                    "name": case["name"],
                    "rejects": case["rejects"],
                    "kind": case["kind"],
                    "category": case["category"],
                    "subject": case["subject"],
                    "note": case.get("note", ""),
                    "matched": all(phase["matched"] for phase in phases),
                    "diagnostic_codes": diagnostic_codes,
                    "phases": phases,
                }
            )
    report = {
        "python": sys.version,
        "ty": await to_thread.run_sync(version, "ty"),
        "sources": {
            filename: sha256(await (directory / filename).read_bytes()).hexdigest()
            for filename in (
                "header.py.txt",
                "cases.json",
                "../dual_typing_parity/bridge.py",
                "application.py",
                "sqlite.py",
                "mariadb.py",
                "columns.py",
                "maria_models.py",
                "check.py",
                "../paired_advanced/body.py",
                "../paired_advanced/contracts.py",
                "../dual_typing_parity/strict_columns.py",
                "../class_body_usage/sqlite.py",
                "../state_declarations/sqlite.py",
                "../paired_advanced/helpers.py",
                "../paired_situations/dual_sqlite.py",
                "../paired_situations/dual.py",
                "../paired_situations/dual_gaps.py",
                "../paired_situations/dual_mariadb.py",
                "../dual_pairing/sqlite.py",
                "../dual_basics/sqlite.py",
                "../dual_backends/core.py",
                "../dual_backends/sqlite.py",
                "../dual_backends/mariadb.py",
                "../dual_finalization/interface.py",
                "../dual_storage/interface.py",
                "../dual_features/records.py",
                "../../snekql/model.py",
                "../../snekql/query.py",
                "../../snekql/storage.py",
                "../../snekql/expressions.py",
                "../../snekql/_aliases.py",
                "../../snekql/_cte.py",
                "../../snekql/_model_materialization.py",
                "../../snekql/sqlite/model.py",
                "../../snekql/sqlite/verbs.py",
                "../../snekql/mariadb/model.py",
                "../../snekql/mariadb/storage.py",
                "../../snekql/_declaration_binding.py",
                "../../snekql/mariadb/verbs.py",
                "../../snekql/runtime.py",
            )
        },
        "observations": observations,
    }
    await (directory / "results.json").write_text(dumps(report, indent=2) + "\n")
    print(
        f"Matched {sum(bool(item['matched']) for item in observations)}/{len(observations)} observations"
    )
    if not all(item["matched"] for item in observations):
        raise SystemExit(1)


if __name__ == "__main__":
    run(main)
