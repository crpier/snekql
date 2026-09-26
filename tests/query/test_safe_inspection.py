"""Redacted query text and explicit per-call value inspection."""

from io import StringIO
from logging import INFO, Logger, StreamHandler
from typing import Annotated, Any, ClassVar

from pydantic import PlainSerializer
from snektest import Param, assert_eq, assert_raises, test

from snekql import mariadb, sqlite


@test(mark="fast")
def default_formatting_hides_bindings() -> None:
    """Default query formatting keeps placeholders without rendering bound secrets."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        token: sqlite.Col[str] = sqlite.Text()

    query = sqlite.select(Account).where(Account.token.eq("private-token"))
    for rendered in (repr(query), str(query)):
        assert "private-token" not in rendered
        assert "<redacted:1>" in rendered
        assert "inlined literals" not in rendered
    assert_eq(query.compile().params, ("private-token",))


@test(mark="fast")
def explicit_inspection_is_local() -> None:
    """Value inspection includes diagnostics without changing subsequent formatting."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        token: sqlite.Col[str] = sqlite.Text()

    query = sqlite.select(Account).where(Account.token.eq("private-token"))
    visible = query.inspect(parameter_visibility="values")
    assert "private-token" in visible
    assert "inlined literals (approximate, not executed)" in visible
    assert_eq(query.inspect(), str(query))
    assert "private-token" not in query.inspect()
    assert "private-token" not in repr(query)


class SQLiteAccount[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[SQLiteAccount[sqlite.Row]]]
    token: sqlite.Col[str] = sqlite.Text()


class MariaDBAccount[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[MariaDBAccount[mariadb.Row]]]
    token: mariadb.Col[str] = mariadb.Text()


@test(
    [Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")],
    [
        Param(kind, name=kind)
        for kind in (
            "select",
            "insert",
            "update",
            "delete",
            "incomplete_select",
            "incomplete_update",
            "incomplete_delete",
        )
    ],
    mark="fast",
)
def query_shapes_hide_secrets(backend: str, kind: str) -> None:
    """Read/write builders and unfinished builders share the redaction policy."""
    namespace: Any = sqlite if backend == "sqlite" else mariadb
    model: Any = SQLiteAccount if backend == "sqlite" else MariaDBAccount
    queries = {
        "select": namespace.select(model).where(model.token.eq("private-token")),
        "insert": namespace.insert(model(token="private-token")),
        "update": namespace.update(model).set(model.token.to("private-token")).all(),
        "delete": namespace.delete(model).where(model.token.eq("private-token")),
        "incomplete_select": namespace.select(model),
        "incomplete_update": namespace.update(model).set(
            model.token.to("private-token")
        ),
        "incomplete_delete": namespace.delete(model),
    }
    query = queries[kind]
    for rendered in (repr(query), str(query), query.inspect()):
        assert "private-token" not in rendered
        assert "inlined literals" not in rendered


@test(mark="fast")
def compilation_failure_does_not_render_exception() -> None:
    """Codec errors can contain secrets, so default formatting omits their text."""

    def refuse(value: str) -> str:
        raise sqlite.ModelValidationError(value)

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        token: sqlite.Col[Annotated[str, PlainSerializer(refuse)]] = sqlite.Text()

    query = sqlite.select(Account).where(Account.token.eq("private-token"))
    assert_eq(repr(query), "<SelectModelQuery inspection unavailable>")
    assert_eq(str(query), "<SelectModelQuery inspection unavailable>")
    with assert_raises(sqlite.ModelValidationError):
        query.compile()


@test(mark="fast")
def ordinary_logging_hides_bindings() -> None:
    """Logging's ordinary string and repr substitutions keep bound values private."""
    output = StringIO()
    handler = StreamHandler(output)
    logger = Logger("safe-inspection", level=INFO)  # noqa: LOG001 - isolate handlers from global logging state
    logger.addHandler(handler)
    query = sqlite.select(SQLiteAccount).where(SQLiteAccount.token.eq("private-token"))
    logger.info("query=%s", query)
    logger.info("query=%r", query)
    assert "private-token" not in output.getvalue()
    assert "<redacted:1>" in output.getvalue()


@test([Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")], mark="fast")
def raw_representation_omits_sql(backend: str) -> None:
    """Raw SQL can contain literals, so its existing representation stays opaque."""
    namespace: Any = sqlite if backend == "sqlite" else mariadb
    statement = namespace.raw("SELECT 'private-literal'", params=("private-binding",))
    for rendered in (repr(statement), str(statement)):
        assert "private" not in rendered
    assert_eq(statement.sql, "SELECT 'private-literal'")


@test(mark="fast")
def compiled_representation_never_formats_parameters() -> None:
    """Structured access stays explicit, even for parameters with unsafe reprs."""

    class Secret:
        def __repr__(self) -> str:
            message = "private-repr"
            raise sqlite.ModelValidationError(message)

    secret = Secret()
    compiled = sqlite.CompiledQuery(backend="sqlite", sql="SELECT ?", params=(secret,))
    assert "private" not in repr(compiled)
    assert "private" not in str(compiled)
    assert compiled.params[0] is secret


@test(mark="fast")
def invalid_visibility_rejected() -> None:
    """Misspelled policies must not silently enable or disable disclosure."""
    query = sqlite.select(SQLiteAccount).all()
    with assert_raises(sqlite.QueryConstructionError):
        query.inspect(parameter_visibility="invalid")  # ty: ignore[invalid-argument-type]


@test(mark="fast")
def query_formatting_never_inlines_encoded_values() -> None:
    """Redacted formatting must not even attempt to render an encoded parameter."""

    class Secret(str):
        __slots__: tuple[str, ...] = ()

        def __repr__(self) -> str:
            message = "must not format secret"
            raise sqlite.ModelValidationError(message)

        def __str__(self) -> str:
            message = "must not inline secret"
            raise sqlite.ModelValidationError(message)

    def encode(value: str) -> Any:
        return Secret(value)

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        token: sqlite.Col[Annotated[str, PlainSerializer(encode)]] = sqlite.Text()

    query = sqlite.select(Account).where(Account.token.eq("private-token"))
    assert "<redacted:1>" in repr(query)
    assert "<redacted:1>" in str(query)
    assert "inspection unavailable" not in repr(query)


@test(mark="fast")
def explicit_inspection_keeps_compilation_errors() -> None:
    """Safe placeholder text is not a substitute for deliberate compilation checks."""
    query = sqlite.select(SQLiteAccount)
    with assert_raises(sqlite.QueryCompilationError):
        query.inspect(parameter_visibility="values")
