"""Proof requested in #593 at Pydantic's public runtime and native ty seams."""

import sys
from json import loads

from anyio import Path, TemporaryDirectory, run_process
from snektest import assert_eq, test

PROOF = Path("research/unparsed_593/proof.py.txt")


@test(mark="slow")
async def adapter_parses_unwrapped_driver_values() -> None:
    """The marker changes neither identity nor runtime type; the adapter parses."""
    completed = await run_process(
        [sys.executable, "-c", await PROOF.read_text()], check=False
    )

    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
    assert_eq(
        completed.stdout.decode(),
        "True int 42 int\nTrue str 42 int\n",
    )


@test(mark="slow")
async def native_checker_requires_parsing_and_retains_the_expected_type() -> None:
    """Clean exact types accompany three independent rejected assignments."""
    source = await PROOF.read_text()
    challenge = source + (
        "\nneeds_parsing: int = raw_age  # expect-error\n"
        "wrong_contract: Unparsed[str] = raw_age  # expect-error\n"
        "wrong_output: str = parsed_age  # expect-error\n"
    )
    async with TemporaryDirectory(prefix="unparsed-proof-") as directory:
        positive = Path(directory) / "positive.py"
        negative = Path(directory) / "negative.py"
        await positive.write_text(source)
        await negative.write_text(challenge)
        command = [
            sys.executable,
            "-m",
            "ty",
            "check",
            "--python",
            sys.executable,
            "--output-format",
            "gitlab",
        ]
        clean = await run_process([*command, str(positive)], check=False)
        assert_eq(
            clean.returncode, 0, msg=clean.stdout.decode() + clean.stderr.decode()
        )
        assert_eq(loads(clean.stdout), [])

        rejected = await run_process([*command, str(negative)], check=False)
        assert_eq(rejected.returncode, 1, msg=rejected.stderr.decode())
        assert_eq(
            [
                (
                    error["location"]["path"],
                    error["location"]["positions"]["begin"]["line"],
                    error["check_name"],
                )
                for error in loads(rejected.stdout)
            ],
            [
                (str(negative), number, "invalid-assignment")
                for number, line in enumerate(challenge.splitlines(), start=1)
                if "# expect-error" in line
            ],
            msg=rejected.stdout.decode(),
        )
