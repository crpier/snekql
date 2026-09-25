"""Edit the actual large declarations, with isolated static and runtime controls."""

from difflib import unified_diff
from hashlib import sha256
from json import dumps, loads

from anyio import Path, TemporaryDirectory, fail_after, run, run_process
from snekql.errors import ModelDeclarationError


async def main() -> None:
    directory = Path(__file__).parent
    root = directory.parent.parent
    reports: list[dict[str, object]] = []
    async with TemporaryDirectory(
        dir=str(root / ".git/approach-situations")
    ) as temporary:
        path = Path(temporary) / "evolution_caller.py"
        for approach in ("nested", "body", "dual"):
            original = await (directory / f"{approach}.py").read_text()
            if approach == "nested":
                added = original.replace(
                    'table_name = "orders"',
                    'table_name = "orders"\n    cancellation_reason: sqlite.Col[str | None] = sqlite.Text()',
                )
                completed_addition = added.replace(
                    "__row__: ClassVar[type[Order]]",
                    "__row__: ClassVar[type[Order]]\n        cancellation_reason: sqlite.Col[str | None] = sqlite.default(None)",
                )
            elif approach == "body":
                added = original.replace(
                    '__tablename__ = "orders"',
                    '__tablename__ = "orders"\n    cancellation_reason: sqlite.Col[str | None] = sqlite.Text(default=None)',
                )
                completed_addition = added
            else:
                added = original.replace(
                    "class Order(sqlite.Model):",
                    "class Order(sqlite.Model):\n    cancellation_reason: sqlite.Col[str | None] = sqlite.Text(default=None)",
                )
                completed_addition = added
            renamed = original.replace(
                "OrderId = NewType",
                'EmailAddress = NewType("EmailAddress", str)\nOrderId = NewType',
            )
            spelling = "customer_email: sqlite.Col[str]"
            updated_spelling = spelling.replace("[str]", "[EmailAddress]")
            stale_type = renamed.replace(spelling, updated_spelling, 1)
            updated_type = renamed.replace(spelling, updated_spelling)
            completed_type = updated_type.replace(
                'customer_email="ada@example.com"',
                'customer_email=EmailAddress("ada@example.com")',
            )
            changed_status = original.replace(
                'Literal["draft", "paid", "cancelled"]',
                'Literal["queued", "paid", "cancelled"]',
            )
            default_spelling = (
                'sqlite.default("draft")'
                if approach == "nested"
                else 'sqlite.Text(default="draft")'
            )
            completed_status = changed_status.replace(
                default_spelling, default_spelling.replace("draft", "queued")
            )
            cases = [
                ("unchanged-control", original, False, False, "draft"),
                ("add-nullable-field", completed_addition, False, False, "draft"),
                ("nominal-email-with-caller", completed_type, False, False, "draft"),
                ("nominal-email-stale-caller", updated_type, True, False, "draft"),
                ("new-status-default", completed_status, False, False, "queued"),
                (
                    "new-status-stale-default",
                    changed_status,
                    approach == "body",
                    True,
                    None,
                ),
            ]
            if approach == "nested":
                cases.extend(
                    [
                        ("add-field-stale-pending", added, False, True, None),
                        ("nominal-email-stale-pending", stale_type, False, True, None),
                    ]
                )
            if approach == "dual":
                generated = original.replace(
                    "class Order(sqlite.Model):",
                    "class Order(sqlite.Model):\n    tracking_code: sqlite.Col[int | sqlite.Omitted] = sqlite.Integer(default=native.LiteralDefault(7))",
                )
                refined = generated.replace(
                    "class OrderRow(Order, sqlite.Row):",
                    "class OrderRow(Order, sqlite.Row):\n    tracking_code: sqlite.Col[int]",
                )
                cases.extend(
                    [
                        ("generated-field-refined", refined, False, False, "draft"),
                        ("generated-field-stale-row", generated, False, True, None),
                    ]
                )
            for label, source, static_error, runtime_error, status in cases:
                if label != "unchanged-control" and source == original:
                    raise ModelDeclarationError(
                        "Source edit did not change the example"
                    )
                binding = "\nsqlite.scaffold(OrderRow)\n" if approach == "dual" else ""
                await path.write_text(
                    source + binding + "\nprint(sample_order().status)\n"
                )
                with fail_after(20):
                    checked = await run_process(
                        [
                            "uv",
                            "run",
                            "ty",
                            "check",
                            str(path),
                            "--output-format",
                            "gitlab",
                        ],
                        check=False,
                    )
                    executed = await run_process(
                        ["uv", "run", "python", str(path)], check=False
                    )
                diagnostics = loads(checked.stdout or b"[]")
                static_matched = checked.returncode == (1 if static_error else 0)
                if static_error:
                    static_matched = (
                        static_matched
                        and bool(diagnostics)
                        and all(
                            item["check_name"]
                            == (
                                "invalid-assignment"
                                if label == "new-status-stale-default"
                                else "invalid-argument-type"
                            )
                            and (
                                "status:"
                                if label == "new-status-stale-default"
                                else "customer_email="
                            )
                            in source.splitlines()[
                                item["location"]["positions"]["begin"]["line"] - 1
                            ]
                            for item in diagnostics
                        )
                    )
                else:
                    static_matched = static_matched and not diagnostics
                stderr = executed.stderr.decode()
                runtime_matched = (
                    executed.returncode == 1
                    and (
                        "ModelValidationError:"
                        if label == "new-status-stale-default"
                        else "ModelDeclarationError:"
                    )
                    in stderr
                    if runtime_error
                    else executed.returncode == 0
                    and executed.stdout.decode().strip() == status
                )
                report = {
                    "approach": approach,
                    "edit": label,
                    "source_sha256": sha256(original.encode()).hexdigest(),
                    "edited_sha256": sha256(source.encode()).hexdigest(),
                    "diff": list(
                        unified_diff(
                            original.splitlines(),
                            source.splitlines(),
                            fromfile=f"{approach}.py",
                            tofile=label,
                            lineterm="",
                        )
                    ),
                    "static_rejects": static_error,
                    "runtime_rejects": runtime_error,
                    "matched": static_matched and runtime_matched,
                    "diagnostics": diagnostics,
                    "runtime_output": executed.stdout.decode().strip(),
                    "runtime_error": next(
                        (
                            line
                            for line in stderr.splitlines()
                            if line.startswith("snekql.errors.")
                        ),
                        None,
                    ),
                    "rejection_stage": (
                        "value construction"
                        if label == "new-status-stale-default"
                        else "declaration"
                    )
                    if runtime_error
                    else None,
                }
                reports.append(report)
                if not report["matched"]:
                    print(dumps(report, indent=2))
        await (directory / "evolution.json").write_text(dumps(reports, indent=2) + "\n")
    if not all(report["matched"] for report in reports):
        raise ModelDeclarationError("A source-edit observation changed")
    print(f"Matched {len(reports)} source-edit observations")


if __name__ == "__main__":
    run(main)
