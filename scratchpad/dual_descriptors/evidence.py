"""Compile actual application queries and compare their algorithms independently of ty."""

import sys
from ast import (
    AST,
    Assign,
    AsyncFunctionDef,
    Call,
    Module,
    Name,
    NodeTransformer,
    Tuple,
    dump,
    parse,
)
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from hashlib import sha256
from importlib.metadata import version
from json import dumps
from typing import Any

from anyio import Path, run, to_thread
from snekql import sqlite

from scratchpad.dual_descriptors import application as dual
from scratchpad.paired_advanced import body
from scratchpad.paired_advanced.contracts import UserId


class TranslationOnly(NodeTransformer):
    """Remove explicit bridge binding; retain every SQL operation and application literal."""

    def __init__(self) -> None:
        self.bindings: dict[str, AST] = {}

    def visit_Assign(self, node: Assign) -> AST | None:
        target = node.targets[0]
        pairs = (
            zip(target.elts, node.value.elts, strict=True)
            if isinstance(target, Tuple) and isinstance(node.value, Tuple)
            else [(target, node.value)]
        )
        entries = list(pairs)
        if all(
            isinstance(value, Call)
            and isinstance(value.func, Name)
            and value.func.id in {"column", "table"}
            for _, value in entries
        ):
            for target, value in entries:
                if isinstance(target, Name) and isinstance(value, Call):
                    self.bindings[target.id] = self.visit(value.args[0])
            return None
        return self.generic_visit(node)

    def visit_Name(self, node: Name) -> AST:
        if node.id in self.bindings:
            return deepcopy(self.bindings[node.id])
        if node.id in {"UserRow", "PostRow"}:
            return Name(id=node.id.removesuffix("Row"), ctx=node.ctx)
        if node.id in {"insert", "insert_many"}:
            return parse("sqlite.insert", mode="eval").body
        return node


class CompilationCapture:
    """An inspection consumer only, never evidence of runtime or static result types."""

    def __init__(self) -> None:
        self.compiled: list[sqlite.CompiledQuery] = []

    async def fetch_all(self, query: Any) -> list[object]:
        self.compiled.append(query.compile())
        return []

    async def execute(self, query: Any) -> object:
        self.compiled.append(query.compile())
        return None

    async def fetch_one_or_none(self, query: Any) -> object:
        self.compiled.append(query.compile())
        return None

    @asynccontextmanager
    async def fetch_chunks(
        self, query: Any, *, size: int
    ) -> AsyncIterator[AsyncIterator[list[object]]]:
        if size < 1:
            raise sqlite.QueryConstructionError("A positive chunk size is required")
        self.compiled.append(query.compile())

        async def empty() -> AsyncIterator[list[object]]:
            for batch in []:
                yield batch

        yield empty()


async def main() -> None:
    directory = Path(__file__).parent
    files = {
        style: parse(await (directory / filename).read_text())
        for style, filename in (
            ("body", "../paired_advanced/body.py"),
            ("dual", "application.py"),
        )
    }
    functions = {
        style: {
            node.name: node for node in tree.body if isinstance(node, AsyncFunctionDef)
        }
        for style, tree in files.items()
    }
    if functions["body"].keys() != functions["dual"].keys():
        raise sqlite.ModelDeclarationError(
            "The compared applications have different operations"
        )
    algorithms: list[str] = []
    for name, first in functions["body"].items():
        second = functions["dual"][name]
        left = dump(Module(body=first.body, type_ignores=[]), include_attributes=False)
        right = dump(
            TranslationOnly().visit(
                Module(body=deepcopy(second.body), type_ignores=[])
            ),
            include_attributes=False,
        )
        if left != right:
            message = f"Application algorithms differ: {name}"
            raise sqlite.QueryConstructionError(message)
        algorithms.append(name)
    arguments: dict[str, tuple[object, ...]] = {
        "referral_chain": (UserId(3),),
        "import_accounts": ([("Barbara", 7), ("Margaret", 9)],),
        "award_bonus": (UserId(2), 5),
        "refresh_nickname": ("Ada", "A"),
        "lookup_account": ("Missing",),
    }
    queries: dict[str, dict[str, list[sqlite.CompiledQuery]]] = {}
    for style, application in (("body", body), ("dual", dual)):
        queries[style] = {}
        for name in algorithms:
            capture = CompilationCapture()
            # This reflection boundary is deliberately erased. check.py separately
            # checks the expressions before function return annotations can hide Any.
            operation: Any = getattr(application, name)
            if name == "stream_accounts":
                async for _ in operation(capture):
                    pass
            else:
                await operation(capture, *arguments.get(name, ()))
            queries[style][name] = capture.compiled
    if queries["body"] != queries["dual"]:
        raise sqlite.QueryConstructionError("SQL or ordered parameters differ")
    scaffold = sqlite.scaffold([body.User, body.Post])
    if scaffold != dual.storage.scaffold(dual.UserRow, dual.PostRow):
        raise sqlite.ModelDeclarationError("Storage declarations differ")
    sources = [path async for path in directory.glob("*.py")]
    report = {
        "python": sys.version,
        "ty": await to_thread.run_sync(version, "ty"),
        "ruff": await to_thread.run_sync(version, "ruff"),
        "sources": {
            path.name: sha256(await path.read_bytes()).hexdigest() for path in sources
        },
        "matching_algorithms": algorithms,
        "scaffold": scaffold,
        "compiled_pairs": {
            name: [{"sql": query.sql, "params": query.params} for query in compiled]
            for name, compiled in queries["body"].items()
        },
    }
    await (directory / "evidence.json").write_text(dumps(report, indent=2) + "\n")
    print(
        f"{len(algorithms)} matching application algorithms and SQL/parameter pairs; two matching model scaffolds"
    )


if __name__ == "__main__":
    run(main)
