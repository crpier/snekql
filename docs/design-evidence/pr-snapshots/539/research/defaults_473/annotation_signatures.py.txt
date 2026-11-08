"""Research-only typing overlay; never execute generated model modules."""

import ast
from dataclasses import dataclass
from typing import Never


def _unsupported(message: str) -> Never:
    raise ValueError(message)


@dataclass(frozen=True)
class _Field:
    name: str
    python_type: str
    namespace: str
    metadata: ast.Call | None
    error_rule: str | None
    sql_type: str
    sql_expression: str
    sql_error: str | None

    def parameter(self) -> str:
        suffix = " = ..." if self.metadata is not None else ""
        return f"{self.name}: {self.python_type}{suffix}"


def _annotation_metadata(annotation: ast.expr) -> tuple[ast.expr, ast.Call | None]:
    if (
        not isinstance(annotation, ast.Subscript)
        or ast.unparse(annotation.value) != "Annotated"
    ):
        return annotation, None
    if not isinstance(annotation.slice, ast.Tuple):
        _unsupported("Expected explicit Annotated metadata")
    logical, *extras = annotation.slice.elts
    if (
        len(extras) != 1
        or not isinstance(extras[0], ast.Call)
        or ast.unparse(extras[0].func) not in ("Default", "Factory")
    ):
        _unsupported("Only explicit Default or Factory metadata is supported")
    metadata = extras[0]
    if len(metadata.args) != 1 or metadata.keywords:
        _unsupported("Expected one positional metadata argument")
    return logical, metadata


def _field(field: ast.AnnAssign, source_lines: list[str]) -> _Field | None:
    if (
        isinstance(field.annotation, ast.Subscript)
        and ast.unparse(field.annotation.value) == "ClassVar"
    ):
        return None
    annotation, metadata = _annotation_metadata(field.annotation)
    if not isinstance(field.target, ast.Name) or not isinstance(
        annotation, ast.Subscript
    ):
        _unsupported("Expected a named column field")
    if not isinstance(annotation.value, ast.Attribute) or annotation.value.attr not in (
        "Col",
        "GenCol",
    ):
        _unsupported("Expected an explicit Col or GenCol annotation")
    if field.target.id == "self":
        _unsupported("A field named self is outside this prototype")
    namespace = ast.unparse(annotation.value.value)
    logical = ast.unparse(annotation.slice)
    if annotation.value.attr == "GenCol":
        logical += f" | {namespace}.PENDING_GENERATION"
    last_line = source_lines[(field.end_lineno or field.lineno) - 1]
    error_rule = (
        last_line.split("# default-error: ", 1)[1]
        if "# default-error: " in last_line
        else None
    )
    if field.value is None:
        _unsupported("Expected an explicit SQL declaration")
    sql_error = (
        last_line.split("# sql-error: ", 1)[1] if "# sql-error: " in last_line else None
    )
    return _Field(
        field.target.id,
        logical,
        namespace,
        metadata,
        error_rule,
        ast.unparse(annotation),
        ast.unparse(field.value),
        sql_error,
    )


def _constructor(model: ast.ClassDef, fields: list[_Field]) -> str:
    if len(model.type_params) != 1 or len(model.bases) != 1:
        _unsupported("Only single-state, single-base models are supported")
    if not fields:
        _unsupported("The prototype requires at least one field")
    namespace = fields[0].namespace
    indent = " " * model.body[0].col_offset
    parameters = ", ".join(field.parameter() for field in fields)
    return (
        f"\n{indent}if _snekql_typing.TYPE_CHECKING:\n"
        f"{indent}    def __init__(self: {model.name}[{namespace}.Pending], *, {parameters}) -> None: ...\n"
    )


def _metadata_check(model: str, field: _Field) -> str:
    if field.metadata is None:
        return ""
    expected = field.python_type
    if ast.unparse(field.metadata.func) == "Factory":
        expected = f"_snekql_typing.Callable[[], {expected}]"
    name = f"_snekql_check_{model}_{field.name}"
    marker = f"  # error: {field.error_rule}" if field.error_rule else ""
    return (
        "\nif _snekql_typing.TYPE_CHECKING:\n"
        f"    def {name}(value: {expected}) -> None: ...\n"
        f"    {name}({ast.unparse(field.metadata.args[0])}){marker}\n"
    )


def _sql_check(model: str, field: _Field) -> str:
    name = f"_snekql_sql_{model}_{field.name}"
    marker = f"  # error: {field.sql_error}" if field.sql_error else ""
    return (
        "\nif _snekql_typing.TYPE_CHECKING:\n"
        f"    def {name}(value: {field.sql_type}) -> None: ...\n"
        f"    {name}({field.sql_expression}){marker}\n"
    )


def _base_name(base: ast.expr) -> str:
    return ast.unparse(base.value if isinstance(base, ast.Subscript) else base)


def _models(module: ast.Module) -> list[ast.ClassDef]:
    models = [
        node
        for node in module.body
        if isinstance(node, ast.ClassDef)
        and any(_base_name(base) == "LeftModel" for base in node.bases)
    ]
    if not models:
        _unsupported("No direct top-level LeftModel declaration was found")
    names = {"LeftModel", *(model.name for model in models)}
    for node in ast.walk(module):
        if (
            isinstance(node, ast.ClassDef)
            and node not in models
            and any(_base_name(base) in names for base in node.bases)
        ):
            _unsupported(
                "Local and inherited model declarations are outside this prototype"
            )
    return models


def _fields(model: ast.ClassDef, lines: list[str]) -> list[_Field]:
    for node in ast.walk(model):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in (
            "__init__",
            "__new__",
        ):
            _unsupported("Custom constructors are outside this prototype")
    for node in model.body:
        if isinstance(
            node, (ast.If, ast.For, ast.While, ast.With, ast.Try, ast.Match)
        ) and any(isinstance(child, ast.AnnAssign) for child in ast.walk(node)):
            _unsupported("Conditional field declarations are outside this prototype")
    return [
        result
        for node in model.body
        if isinstance(node, ast.AnnAssign)
        if (result := _field(node, lines)) is not None
    ]


def _import_position(module: ast.Module) -> int:
    position = 0
    for index, node in enumerate(module.body):
        docstring = (
            index == 0
            and isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
        future_import = isinstance(node, ast.ImportFrom) and node.module == "__future__"
        if not docstring and not future_import:
            break
        position = node.end_lineno or position
    return position


def typing_overlay(source: str) -> str:
    """Render typing-only constructors and checks for explicit top-level LeftModels.

    This is a narrow AST experiment, not a production source transformer. It
    never imports, evaluates or executes the source or its default expressions.
    """
    module = ast.parse(source)
    lines = source.splitlines()
    insertions: list[tuple[int, str]] = []
    checks: list[str] = []
    for model in _models(module):
        fields = _fields(model, lines)
        if model.end_lineno is None:
            _unsupported("Missing class source location")
        insertions.append((model.end_lineno, _constructor(model, fields)))
        checks.extend(_metadata_check(model.name, field) for field in fields)
        checks.extend(_sql_check(model.name, field) for field in fields)
    insertions.append((_import_position(module), "\nimport typing as _snekql_typing\n"))
    for position, addition in sorted(insertions, reverse=True):
        lines[position:position] = addition.splitlines()
    return "\n".join(lines) + "\n" + "".join(checks)
