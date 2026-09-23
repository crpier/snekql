"""Run throwaway type-checker experiments; this does not execute SQL."""

import asyncio
from argparse import ArgumentParser
from json import dumps
from pathlib import Path


async def main() -> None:
    """Retain each compiler diagnostic, including unsafe accepted examples."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    output: object = parser.parse_args().output
    if not isinstance(output, Path):
        parser.error("--output must be a path")
    await asyncio.to_thread(output.mkdir, parents=True, exist_ok=True)
    source = Path(__file__).resolve().parent
    project = source.parents[1]
    requirements = {
        "selector_positive": True,
        "selector_incompatible": False,
        "selector_missing": False,
        "schema_positive": True,
        "schema_real_labels": True,
        "schema_incompatible": False,
        "schema_missing": False,
        "keyed_positive": True,
        "keyed_wrong_field": False,
        "specialized_positive": True,
        "specialized_real_labels": True,
        "specialized_negative_domain": False,
        "specialized_negative_missing": False,
        "specialized_negative_extra": False,
        "specialized_negative_family": False,
        "specialized_negative_result": False,
        "specialized_negative_nullable": False,
        "specialized_negative_production_family": False,
        "specialized_negative_left_join": False,
        "variadic_widening": True,
        "structural_positive": True,
        "structural_wrong_field": False,
        "layout_union_positive": True,
        "layout_union_incompatible": False,
        "layout_union_missing": False,
        "layout_union_negative_nullable": False,
        "layout_union_left_join": True,
        "layout_union_wide": True,
    }
    reports: list[dict[str, object]] = []
    for name, should_accept in requirements.items():
        process = await asyncio.create_subprocess_exec(
            "uv",
            "run",
            "ty",
            "check",
            "--project",
            str(project),
            str(source / f"{name}.py"),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await process.communicate()
        await asyncio.to_thread((output / f"{name}.log").write_bytes, stdout)
        accepted = process.returncode == 0
        reports.append(
            {
                "case": name,
                "should_accept": should_accept,
                "accepted": accepted,
                "requirement_met": accepted == should_accept,
                "exit_code": process.returncode,
            }
        )
    await asyncio.to_thread(
        (output / "assessment.json").write_text,
        dumps(reports, indent=2) + "\n",
    )
    print(dumps(reports, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
