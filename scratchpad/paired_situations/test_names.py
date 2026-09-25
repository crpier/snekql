"""Comparison vocabulary must not introduce new column semantics."""

from ast import Attribute, parse, walk
from pathlib import Path

from anyio import to_thread
from snektest import Param, assert_eq, assert_is, test


@test(
    [
        Param(value=("sqlite", "Col", "Field"), name="sqlite-col"),
        Param(value=("sqlite", "FKCol", "ForeignField"), name="sqlite-fk"),
        Param(value=("mariadb", "Col", "Field"), name="maria-col"),
        Param(value=("mariadb", "FKCol", "ForeignField"), name="maria-fk"),
        Param(value=("mariadb", "JsonCol", "JsonField"), name="maria-json"),
    ],
    mark="fast",
)
def column_names_alias_the_existing_descriptors(case: tuple[str, str, str]) -> None:
    from scratchpad.fetched_stress import mariadb, sqlite
    from scratchpad.paired_situations import nested_mariadb, nested_sqlite

    backend, name, previous = case
    originals = {"sqlite": sqlite, "mariadb": mariadb}
    renamed = {"sqlite": nested_sqlite, "mariadb": nested_mariadb}
    assert_is(getattr(renamed[backend], name), getattr(originals[backend], previous))


@test(mark="fast")
async def review_files_use_native_column_vocabulary() -> None:
    directory = Path(__file__).parent
    for filename in ("nested.py", "body.py", "dual.py"):
        source = await to_thread.run_sync((directory / filename).read_text)
        old_names = [
            node.attr
            for node in walk(parse(source))
            if isinstance(node, Attribute)
            and node.attr in {"Field", "ForeignField", "JsonField"}
        ]
        assert_eq(old_names, [])
