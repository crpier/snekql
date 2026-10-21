"""Pagination retains its strict public call contract on every SELECT shape."""

import os
import subprocess
import sys
from enum import IntEnum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, ClassVar

from pydantic import BaseModel, ValidationError
from snektest import (
    Param,
    assert_eq,
    assert_isinstance,
    assert_not_in,
    assert_raises,
    test,
)

from snekql import mariadb, sqlite


class SqlMember[S = sqlite.Pending](sqlite.Model[S]):
    """SQLite source for model and compound selections."""

    __row_type__: ClassVar[sqlite.ReadType[SqlMember[sqlite.Row]]]
    member_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)


class MariaMember[S = mariadb.Pending](mariadb.Model[S]):
    """MariaDB source sharing the result contract."""

    __row_type__: ClassVar[mariadb.ReadType[MariaMember[mariadb.Row]]]
    member_id: mariadb.Col[int] = mariadb.Integer(primary_key=True)


class MemberId(BaseModel):
    """Named result required by compound selections."""

    member_id: int


def query_for(backend: str, shape: str) -> Any:
    """Deliberately exercise the public interface as an untyped caller."""
    if backend == "sqlite":
        query = sqlite.select(SqlMember)
        named = query.project(
            MemberId, member_id=SqlMember.member_id.label("member_id")
        )
        return named.union_all(named) if shape == "compound" else query
    maria_query = mariadb.select(MariaMember)
    maria_named = maria_query.project(
        MemberId, member_id=MariaMember.member_id.label("member_id")
    )
    return maria_named.union_all(maria_named) if shape == "compound" else maria_query


BACKENDS = [Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")]
SHAPES = [Param("model", name="model"), Param("compound", name="compound")]


@test(BACKENDS, SHAPES, mark="fast")
def pagination_rejects_invalid_values_and_call_shapes(backend: str, shape: str) -> None:
    """Bad calls keep domain errors, Pydantic causes and redacted messages."""
    query = query_for(backend, shape)
    calls = [
        ((True,), {}),
        ((-1,), {}),
        ((1.0,), {}),
        (("private-pagination-input",), {}),
        ((None,), {}),
        ((), {}),
        ((1, 2), {}),
        ((1,), {"value": 2}),
        ((1,), {"unexpected": 2}),
    ]
    for name in ("limit", "offset"):
        method = getattr(query, name)
        for args, kwargs in calls:
            with assert_raises(sqlite.QueryConstructionError) as error:
                method(*args, **kwargs)
            assert_isinstance(error.exception.__cause__, ValidationError)
            assert_not_in("private-pagination-input", str(error.exception))


class PageSize(IntEnum):
    """Integer subtypes still use the existing normalizing validator."""

    TWO = 2


@test(BACKENDS, SHAPES, mark="fast")
def valid_pagination_keeps_values_and_independent_branches(
    backend: str, shape: str
) -> None:
    """Zero, large ints, keywords and integer subtypes keep their SQL meaning."""
    base = query_for(backend, shape)
    empty = base.limit(0).offset(0)
    keyword = base.limit(value=PageSize.TWO).offset(value=1)
    subtype = base.limit(PageSize.TWO).offset(1)
    large = base.limit(2**70)
    assert_eq(base.compile().params, ())
    assert_eq(empty.compile().params, (0, 0))
    assert_eq(empty.compile().sql.count("LIMIT"), 1)
    assert_eq(keyword.compile().params, (2, 1))
    assert_eq(subtype.compile().params, (2, 1))
    assert_eq(type(subtype.compile().params[0]), int)
    assert_eq(large.compile().params, (2**70,))


@test(SHAPES, mark="medium")
async def pagination_applies_to_rows_without_changing_the_base(shape: str) -> None:
    """Zero and independent slices apply to ordinary and whole compound results."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001_members": sqlite.scaffold([SqlMember])})
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.insert_many(
                    SqlMember, [SqlMember(member_id=number) for number in (1, 2, 3)]
                )
            )
            base: Any = sqlite.select(SqlMember).order_by(SqlMember.member_id.asc())
            expected = [1, 2, 3]
            page = [2, 3]
            if shape == "compound":
                token = SqlMember.member_id.label("member_id")
                left = sqlite.select(SqlMember).project(MemberId, member_id=token)
                combined = left.union_all(left)
                base = combined.order_by(combined.column(token).asc())
                expected = [1, 1, 2, 2, 3, 3]
                page = [1, 2]
            empty = base.limit(0)
            sliced = base.limit(2).offset(1)
            assert_eq(await transaction.fetch_all(empty), [])
            assert_eq(
                [row.member_id for row in await transaction.fetch_all(sliced)], page
            )
            assert_eq(
                [row.member_id for row in await transaction.fetch_all(base)], expected
            )


@test(mark="medium")
def pagination_respects_installed_validation_plugins() -> None:
    """A real plugin may reject even a valid integer at the public builder seam."""
    plugin = """
class Handler:
    def on_enter(self, input, **kwargs):
        raise ValueError("pagination blocked by plugin")

class Plugin:
    def new_schema_validator(self, schema, schema_type, path, kind, config, settings):
        if kind == "validate_call" and path.name.endswith((".limit", ".offset")):
            return Handler(), None, None
        return None, None, None

plugin = Plugin()
"""
    program = """
from typing import ClassVar
from pydantic import BaseModel
from snekql import sqlite

class Member[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Member[sqlite.Row]]]
    member_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)

class Result(BaseModel):
    member_id: int

base = sqlite.select(Member)
named = base.project(Result, member_id=Member.member_id.label("member_id"))
for query in (base, named.union_all(named)):
    for name in ("limit", "offset"):
        method = getattr(query, name)
        for args, kwargs in (((1,), {}), ((), {"value": 1})):
            try:
                method(*args, **kwargs)
            except ValueError as error:
                assert str(error) == "pagination blocked by plugin", str(error)
            else:
                raise AssertionError("pagination bypassed plugin policy")
"""
    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "pagination_plugin.py").write_text(plugin)
        metadata = root / "snekql_pagination_plugin-0.0.0.dist-info"
        metadata.mkdir()
        (metadata / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: snekql-pagination-plugin\nVersion: 0.0.0\n"
        )
        (metadata / "entry_points.txt").write_text(
            "[pydantic]\npagination = pagination_plugin:plugin\n"
        )
        assert sqlite.__file__ is not None
        package_root = Path(sqlite.__file__).resolve().parents[2]
        environment = dict(os.environ)
        environment.pop("PYDANTIC_DISABLE_PLUGINS", None)
        environment["PYTHONPATH"] = os.pathsep.join(
            (str(root), str(package_root), environment.get("PYTHONPATH", ""))
        )
        result = subprocess.run(
            [sys.executable, "-c", program],
            cwd=package_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    assert_eq(result.returncode, 0, msg=result.stdout + result.stderr)
