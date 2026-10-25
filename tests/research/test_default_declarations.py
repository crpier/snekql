"""Static-only declaration experiments for #473; never import generated callers."""

import sys
from json import loads

from anyio import Path, TemporaryDirectory, fail_after, run_process
from snektest import Param, assert_eq, assert_true, test


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [
        Param(
            (
                "tagged",
                "database.Model",
                "database.Integer(default=database.LiteralDefault(7))",
            ),
            name="tagged",
        ),
        Param(
            ("split-implicit", "ProbeModel", "SplitInteger(server_default=7)"),
            name="split-implicit",
        ),
        Param(
            (
                "dedicated",
                "ProbeModel",
                "DatabaseDefault(database.Integer(), default=7)",
            ),
            name="dedicated",
        ),
        Param(
            ("renamed-python", "ProbeModel", "PythonInteger(python_default=7)"),
            name="renamed-python",
        ),
        Param(
            (
                "split",
                "ProbeModel",
                "SplitInteger(server_default=7, default=database.PENDING_GENERATION)",
            ),
            name="split",
        ),
    ],
    mark="slow",
)
async def default_declaration_typing_observations(
    backend: str, candidate: tuple[str, str, str]
) -> None:
    """Record supported spellings and exact failures, not runtime semantics."""
    name, base, expression = candidate
    source = (await Path("research/defaults_473/consumer.py.txt").read_text()).replace(
        "__BACKEND__", backend
    )
    source = source.replace("database.Model[S]", f"{base}[S]").replace(
        "__DECLARATION__", expression
    )
    source = source.replace(
        "__BAD_DEFAULT__",
        expression.replace("=7", '="wrong"').replace(
            "LiteralDefault(7)", 'LiteralDefault("wrong")'
        ),
    )
    if name in ("split-implicit", "renamed-python"):
        source = source.replace(
            "# omission-probe", "# error: missing-argument"
        ).replace("# error: invalid-assignment", "# accepted-mismatch")
    if name == "renamed-python":
        source = source.replace("database.GenCol[int]", "database.Col[int]").replace(
            "int | database.PENDING_GENERATION", "int"
        )
    if name != "tagged":
        preamble = await Path("research/defaults_473/declarations.py.txt").read_text()
        preamble = preamble.replace("__BACKEND__", backend).replace(
            "__META_MODULE__", f"snekql.{backend}.model"
        )
        source = preamble + "\n" + source
    await assert_paired_typing(source)


async def assert_paired_typing(source: str) -> None:
    """Require clean controls and exactly the marked diagnostics in the challenge."""
    async with TemporaryDirectory(prefix="snekql-defaults-473-") as directory:
        positive = Path(directory) / "positive.py"
        negative = Path(directory) / "negative.py"
        await positive.write_text(
            "\n".join(line for line in source.splitlines() if "# error:" not in line)
        )
        await negative.write_text(source)
        expected_errors = [
            (index, line.split("# error: ")[1])
            for index, line in enumerate(source.splitlines(), 1)
            if "# error: " in line
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
                        str(path),
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


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [Param(name, name=name) for name in ("tagged", "split", "dedicated")],
    mark="slow",
)
async def viable_defaults_cover_consumer_examples(backend: str, candidate: str) -> None:
    """Ordinary defaults, factories, IDs, clocks and nullable inputs retain types."""
    source = await Path("research/defaults_473/examples.py.txt").read_text()
    if candidate == "tagged":
        literal = "database.Integer(default=database.LiteralDefault(7))"
        boolean = "database.Integer(default=database.LiteralDefault(False))"
        clock = "database.Text(default=database.CurrentTimestamp)"
        nullable = 'database.Text(default=database.LiteralDefault("fallback"))'
        null_default = "database.Text(default=database.LiteralDefault(None))"
        base = "database.Model"
    elif candidate == "split":
        literal = "SplitInteger(server_default=7, default=database.PENDING_GENERATION)"
        boolean = (
            "SplitInteger(server_default=False, default=database.PENDING_GENERATION)"
        )
        clock = "SplitText(server_default=database.CurrentTimestamp, default=database.PENDING_GENERATION)"
        nullable = (
            'SplitText(server_default="fallback", default=database.PENDING_GENERATION)'
        )
        null_default = (
            "SplitText(server_default=None, default=database.PENDING_GENERATION)"
        )
        base = "ProbeModel"
    else:
        literal = "DatabaseDefault(database.Integer(), default=7)"
        boolean = "DatabaseDefault(database.Integer(), default=False)"
        clock = "DatabaseDefault(database.Text(), default=database.CurrentTimestamp)"
        nullable = 'DatabaseDefault(database.Text(), default="fallback")'
        null_default = "DatabaseDefault(database.Text(), default=None)"
        base = "ProbeModel"
    for key, value in (
        ("__BACKEND__", backend),
        ("__BASE__", base),
        ("__LITERAL__", literal),
        ("__BOOL__", boolean),
        ("__CLOCK__", clock),
        ("__NULLABLE__", nullable),
        ("__NULL_DEFAULT__", null_default),
    ):
        source = source.replace(key, value)
    if candidate != "tagged":
        preamble = await Path("research/defaults_473/declarations.py.txt").read_text()
        source = (
            preamble.replace("__BACKEND__", backend).replace(
                "__META_MODULE__", f"snekql.{backend}.model"
            )
            + "\n"
            + source
        )
    await assert_paired_typing(source)


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    mark="slow",
)
async def excluded_fields_lose_explicit_overrides(backend: str) -> None:
    """Making generated fields init=False is not a substitute for a default."""
    preamble = await Path("research/defaults_473/declarations.py.txt").read_text()
    source = await Path("research/defaults_473/excluded.py.txt").read_text()
    source = (
        (preamble + "\n" + source)
        .replace("__BACKEND__", backend)
        .replace("__META_MODULE__", f"snekql.{backend}.model")
    )
    await assert_paired_typing(source)
