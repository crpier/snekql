"""Static-only follow-up for flatter default declarations in #473."""

from anyio import Path
from snektest import Param, assert_in, test

from tests.research.test_default_declarations import assert_paired_typing


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [
        Param(
            (
                "ServerInteger(server_default=7)",
                'ServerInteger(server_default="wrong")',
            ),
            name="unregistered-function",
        ),
        Param(
            ("server.Integer(default=7)", 'server.Integer(default="wrong")'),
            name="server-namespace",
        ),
        Param(
            ("ServerInteger(7)", 'ServerInteger("wrong")'), name="prefixed-positional"
        ),
        Param(
            (
                'LocatedInteger(default=7, default_on="database")',
                'LocatedInteger(default="wrong", default_on="database")',
            ),
            name="location-selector",
        ),
    ],
    mark="slow",
)
async def flat_declarations_keep_omission_and_overrides(
    backend: str, expressions: tuple[str, str]
) -> None:
    """A descriptor-valued default may not need field-specifier registration."""
    declarations = await Path(
        "research/defaults_473/flat_declarations.py.txt"
    ).read_text()
    consumer = await Path("research/defaults_473/consumer.py.txt").read_text()
    source = (
        (declarations + "\n" + consumer.replace("database.Model[S]", "FlatModel[S]"))
        .replace("__BACKEND__", backend)
        .replace("__META_MODULE__", f"snekql.{backend}.model")
    )
    source = source.replace("__DECLARATION__", expressions[0]).replace(
        "__BAD_DEFAULT__", expressions[1]
    )
    await assert_paired_typing(source)


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [
        Param(
            (
                "FlatInteger()",
                "FlatInteger.server_default(7)",
                'FlatInteger.server_default("wrong")',
            ),
            name="class-constructor-blocked",
        ),
        Param(
            (
                "CallableInteger()",
                "CallableInteger.server_default(7)",
                'CallableInteger.server_default("wrong")',
            ),
            name="callable-factory",
        ),
    ],
    mark="slow",
)
async def named_factories_lose_required_field_check(
    backend: str, expressions: tuple[str, str, str]
) -> None:
    """Record the missing-required-input regression in class/callable forms."""
    declarations = await Path(
        "research/defaults_473/flat_declarations.py.txt"
    ).read_text()
    consumer = await Path("research/defaults_473/consumer.py.txt").read_text()
    source = (
        (declarations + "\n" + consumer.replace("database.Model[S]", "FlatModel[S]"))
        .replace("__BACKEND__", backend)
        .replace("__META_MODULE__", f"snekql.{backend}.model")
    )
    source = source.replace("database.Text()", expressions[0])
    source = source.replace("database.Col[str]", "database.Col[int]").replace(
        'name="Ada"', "name=1"
    )
    source = source.replace("__DECLARATION__", expressions[1]).replace(
        "__BAD_DEFAULT__", expressions[2]
    )
    source = source.replace("# error: missing-argument", "# accepted-required-omission")
    await assert_paired_typing(source)


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [Param(name, name=name) for name in ("functions", "namespace", "selector")],
    mark="slow",
)
async def flat_defaults_cover_full_consumer_examples(
    backend: str, candidate: str
) -> None:
    """Flatter forms retain exact clock, nullable, factory and Row result types."""
    declarations = await Path(
        "research/defaults_473/flat_declarations.py.txt"
    ).read_text()
    source = await Path("research/defaults_473/examples.py.txt").read_text()
    if candidate == "functions":
        values = (
            "database.Model",
            "ServerInteger(7)",
            "ServerInteger(False)",
            "ServerText(database.CurrentTimestamp)",
            'ServerText("fallback")',
            "ServerText(None)",
        )
        identity = "ServerInteger(primary_key=True, auto_increment=True)"
    elif candidate == "namespace":
        values = (
            "database.Model",
            "server.Integer(7)",
            "server.Integer(False)",
            "server.Text(database.CurrentTimestamp)",
            'server.Text("fallback")',
            "server.Text(None)",
        )
        identity = "server.Integer(primary_key=True, auto_increment=True)"
    else:
        values = (
            "FlatModel",
            'LocatedInteger(default=7, default_on="database")',
            'LocatedInteger(default=False, default_on="database")',
            'LocatedText(default=database.CurrentTimestamp, default_on="database")',
            'LocatedText(default="fallback", default_on="database")',
            'LocatedText(default=None, default_on="database")',
        )
        identity = "database.Integer(primary_key=True, auto_increment=True, default=database.PENDING_GENERATION)"
    for key, value in zip(
        (
            "__BASE__",
            "__LITERAL__",
            "__BOOL__",
            "__CLOCK__",
            "__NULLABLE__",
            "__NULL_DEFAULT__",
        ),
        values,
        strict=True,
    ):
        source = source.replace(key, value)
    original_identity = "database.Integer(\n        primary_key=True, auto_increment=True, default=database.PENDING_GENERATION\n    )"
    assert_in(original_identity, source)
    source = source.replace(original_identity, identity)
    source = (
        (declarations + "\n" + source)
        .replace("__BACKEND__", backend)
        .replace("__META_MODULE__", f"snekql.{backend}.model")
    )
    await assert_paired_typing(source)


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [Param(name, name=name) for name in ("selector_modes", "fluent_blocked")],
    mark="slow",
)
async def flat_modes_and_blocked_chaining_have_exact_controls(
    backend: str, template: str
) -> None:
    """Distinguish a working selector from a tempting but rejected fluent form."""
    declarations = await Path(
        "research/defaults_473/flat_declarations.py.txt"
    ).read_text()
    source = await Path(f"research/defaults_473/{template}.py.txt").read_text()
    source = (
        (declarations + "\n" + source)
        .replace("__BACKEND__", backend)
        .replace("__META_MODULE__", f"snekql.{backend}.model")
    )
    await assert_paired_typing(source)


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    mark="slow",
)
async def registering_server_helper_restores_required_field_behavior(
    backend: str,
) -> None:
    """The same call loses omission when registered as a field specifier."""
    declarations = await Path(
        "research/defaults_473/flat_declarations.py.txt"
    ).read_text()
    assert_in("field_specifiers=(", declarations)
    declarations = declarations.replace(
        "field_specifiers=(", "field_specifiers=(ServerInteger,"
    )
    consumer = await Path("research/defaults_473/consumer.py.txt").read_text()
    consumer = (
        consumer.replace("database.Model[S]", "FlatModel[S]")
        .replace("__DECLARATION__", "ServerInteger(server_default=7)")
        .replace("__BAD_DEFAULT__", 'ServerInteger(server_default="wrong")')
    )
    consumer = consumer.replace(
        "# omission-probe", "# error: missing-argument"
    ).replace("# error: invalid-assignment", "# accepted-mismatch")
    source = (
        (declarations + "\n" + consumer)
        .replace("__BACKEND__", backend)
        .replace("__META_MODULE__", f"snekql.{backend}.model")
    )
    await assert_paired_typing(source)
