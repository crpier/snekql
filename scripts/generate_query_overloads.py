"""Generate finite projection and RETURNING overloads in ``snekql.query``."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

MAX_PROJECTION_WIDTH = 8
QUERY_PATH = Path(__file__).parents[1] / "snekql" / "query.py"


def _replace_generated(source: str, name: str, generated: str) -> str:
    start_marker = f"    # BEGIN GENERATED {name}\n"
    end_marker = f"    # END GENERATED {name}\n"
    if name == "SELECT OVERLOADS":
        start_marker = start_marker.removeprefix("    ")
        end_marker = end_marker.removeprefix("    ")
    before, separator, remainder = source.partition(start_marker)
    if not separator:
        message = f"missing generated start marker: {name}"
        raise ValueError(message)
    _, separator, after = remainder.partition(end_marker)
    if not separator:
        message = f"missing generated end marker: {name}"
        raise ValueError(message)
    return f"{before}{start_marker}{generated}{end_marker}{after}"


def _returning_overloads(
    *, owner: str, read: str | None, value_query: str, tuple_query: str
) -> str:
    blocks: list[str] = []
    for width in range(1, MAX_PROJECTION_WIDTH + 1):
        type_params = ", ".join(f"T{index}" for index in range(1, width + 1))
        fields = "".join(
            f"        field{index}: Attr[Any, Any, {owner}, Any, T{index}],\n"
            for index in range(1, width + 1)
        )
        result_args = [owner]
        if read is not None:
            result_args.append(read)
        result_args.extend(f"T{index}" for index in range(1, width + 1))
        query = value_query if width == 1 else tuple_query
        blocks.append(
            "    @overload\n"
            f"    def returning[{type_params}](\n"
            "        self,\n"
            f"{fields}"
            "        /,\n"
            f"    ) -> {query}[{', '.join(result_args)}]: ...\n\n"
        )
    return "".join(blocks)


def _select_overloads() -> str:
    blocks: list[str] = []
    for width in range(2, MAX_PROJECTION_WIDTH + 1):
        type_params = ",\n    ".join(
            item
            for index in range(1, width + 1)
            for item in (f"Owner{index}T: Table[Any]", f"T{index}")
        )
        fields = "".join(
            f"    field{index}: Attr[Any, Any, Owner{index}T, Any, T{index}]\n"
            f"    | Aggregate[Owner{index}T, T{index}, Any]\n"
            + ("" if index == 1 else f"    | Scalar[Owner{index}T, T{index}, Any]\n")
            + f"    | DialectSelectable[Owner{index}T, T{index}],\n"
            for index in range(1, width + 1)
        )
        owners = " | ".join(f"Owner{index}T" for index in range(1, width + 1))
        values = ", ".join(f"T{index}" for index in range(1, width + 1))
        blocks.append(
            "@overload\n"
            "def select[\n"
            f"    {type_params},\n"
            "](\n"
            f"{fields}"
            "    /,\n"
            f") -> SelectTupleQuery[Owner1T, {owners}, {values}]: ...\n\n\n"
        )
    return "".join(blocks)


def generated_query_source(source: str) -> str:
    """Return ``query.py`` with every generated overload region refreshed."""

    source = _replace_generated(
        source,
        "INSERT RETURNING OVERLOADS",
        _returning_overloads(
            owner="OwnerT",
            read=None,
            value_query="InsertReturningValueQuery",
            tuple_query="InsertReturningTupleQuery",
        ),
    )
    source = _replace_generated(
        source,
        "INSERT MANY RETURNING OVERLOADS",
        _returning_overloads(
            owner="OwnerT",
            read=None,
            value_query="InsertManyReturningValueQuery",
            tuple_query="InsertManyReturningTupleQuery",
        ),
    )
    source = _replace_generated(
        source,
        "UPDATE RETURNING OVERLOADS",
        _returning_overloads(
            owner="ModelT",
            read="ReadT",
            value_query="UpdateReturningValueQuery",
            tuple_query="UpdateReturningTupleQuery",
        ),
    )
    source = _replace_generated(
        source,
        "DELETE RETURNING OVERLOADS",
        _returning_overloads(
            owner="ModelT",
            read="ReadT",
            value_query="DeleteReturningValueQuery",
            tuple_query="DeleteReturningTupleQuery",
        ),
    )
    source = _replace_generated(source, "SELECT OVERLOADS", _select_overloads())
    formatted = subprocess.run(  # noqa: S603
        [
            str(Path(sys.executable).with_name("ruff")),
            "format",
            "--stdin-filename",
            str(QUERY_PATH),
            "-",
        ],
        check=True,
        capture_output=True,
        input=source,
        text=True,
    )
    return formatted.stdout


def main() -> None:
    """Write generated overloads, or fail when ``--check`` detects drift."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    source = QUERY_PATH.read_text()
    generated = generated_query_source(source)
    if arguments.check:
        if generated != source:
            message = "snekql/query.py generated overloads are stale"
            raise SystemExit(message)
        return
    QUERY_PATH.write_text(generated)


if __name__ == "__main__":
    main()
