"""Default-policy research for #473: native ty only, no source projection."""

from anyio import Path
from snektest import Param, test

from tests.research.test_default_declarations import assert_paired_typing


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    mark="slow",
)
async def explicit_policies_preserve_ownership_required_inputs_and_exact_types(
    backend: str,
) -> None:
    declarations = await Path(
        "research/defaults_473/policy_declarations.py.txt"
    ).read_text()
    consumer = await Path("research/defaults_473/policy_basic.py.txt").read_text()
    source = (
        (declarations + "\n" + consumer)
        .replace("__BACKEND__", backend)
        .replace("__META_MODULE__", f"snekql.{backend}.model")
    )
    await assert_paired_typing(source)


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    mark="slow",
)
async def python_policy_checks_factories_constructed_values_and_nullable_inputs(
    backend: str,
) -> None:
    declarations = await Path(
        "research/defaults_473/policy_declarations.py.txt"
    ).read_text()
    imports = "from typing import ClassVar, assert_type\n"
    consumer = await Path("research/defaults_473/policy_factories.py.txt").read_text()
    source = (
        (declarations + "\n" + imports + consumer)
        .replace("__BACKEND__", backend)
        .replace("__META_MODULE__", f"snekql.{backend}.model")
    )
    await assert_paired_typing(source)


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    mark="slow",
)
async def server_policy_checks_clocks_null_and_independent_required_generation(
    backend: str,
) -> None:
    declarations = await Path(
        "research/defaults_473/policy_declarations.py.txt"
    ).read_text()
    imports = "from typing import ClassVar, assert_type\n"
    consumer = await Path("research/defaults_473/policy_server.py.txt").read_text()
    source = (
        (declarations + "\n" + imports + consumer)
        .replace("__BACKEND__", backend)
        .replace("__META_MODULE__", f"snekql.{backend}.model")
    )
    await assert_paired_typing(source)


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    mark="slow",
)
async def policy_only_default_channel_rejects_implicit_ownership(backend: str) -> None:
    declarations = await Path(
        "research/defaults_473/policy_declarations.py.txt"
    ).read_text()
    consumer = """
PolicyInteger(default=PythonDefault(False))
PolicyInteger(default=ServerDefault(False))
PolicyText(default=ServerDefault(database.CurrentTimestamp))
PolicyInteger(default=False)  # error: no-matching-overload
PolicyText(default=database.CurrentTimestamp)  # error: no-matching-overload
PolicyInteger(default=database.LiteralDefault(False))  # error: no-matching-overload

from typing import ClassVar

class Unowned[S = database.Pending](PolicyModel[S]):
    __row_type__: ClassVar[database.ReadType[Unowned[database.Row]]]
    bare: database.Col[bool] = PolicyInteger(default=False)  # error: no-matching-overload
    clock: database.GenCol[database.UtcDatetime] = PolicyText(default=database.CurrentTimestamp)  # error: no-matching-overload
    old: database.GenCol[bool] = PolicyInteger(default=database.LiteralDefault(False))  # error: no-matching-overload
"""
    source = (
        (declarations + "\n" + consumer)
        .replace("__BACKEND__", backend)
        .replace("__META_MODULE__", f"snekql.{backend}.model")
    )
    await assert_paired_typing(source)


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    mark="slow",
)
async def policy_constructors_without_defaults_keep_required_col_and_gencol_inputs(
    backend: str,
) -> None:
    declarations = await Path(
        "research/defaults_473/policy_declarations.py.txt"
    ).read_text()
    imports = "from typing import ClassVar, assert_type\n"
    consumer = await Path("research/defaults_473/policy_required.py.txt").read_text()
    source = (
        (declarations + "\n" + imports + consumer)
        .replace("__BACKEND__", backend)
        .replace("__META_MODULE__", f"snekql.{backend}.model")
    )
    await assert_paired_typing(source)
