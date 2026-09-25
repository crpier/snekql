"""Matched storage, compiled queries, declaration cost, and isolated consumer lint."""

from ast import AnnAssign, ClassDef, Constant, ImportFrom, Name, parse, walk
from dataclasses import asdict
from hashlib import sha256
from json import dumps, loads

from anyio import Path, TemporaryDirectory, run, run_process
from snekql.errors import ModelDeclarationError

from scratchpad.paired_situations import body as b
from scratchpad.paired_situations import dual as d
from scratchpad.paired_situations import nested as n


def _json_value(value: object) -> object:
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    message = f"Unexpected encoded parameter: {type(value).__name__}"
    raise ModelDeclarationError(message)


async def main() -> None:
    directory = Path(__file__).parent
    reports: dict[str, object] = {}
    lint_args = [
        "uv",
        "run",
        "ruff",
        "check",
        "--isolated",
        "--target-version",
        "py314",
        "--select",
        "F,UP037",
        "--output-format",
        "json",
    ]
    for name in ("nested", "body", "dual"):
        source = await (directory / f"{name}.py").read_text()
        syntax = parse(source)
        if any(
            isinstance(node, ImportFrom) and node.module == "__future__"
            for node in walk(syntax)
        ) or any(
            isinstance(child, Constant) and isinstance(child.value, str)
            for node in walk(syntax)
            if isinstance(node, ClassDef)
            for base in node.bases
            for child in walk(base)
        ):
            raise ModelDeclarationError(
                "Review files require deferred annotations, not quoted bases or future imports"
            )
        lint = await run_process(
            [*lint_args, str(directory / f"{name}.py")], check=False
        )
        if lint.returncode:
            raise ModelDeclarationError("Review file requires a lint exception")
        order = next(
            node
            for node in syntax.body
            if isinstance(node, ClassDef) and node.name == "Order"
        )
        contracts = [
            order,
            *(
                node
                for node in order.body
                if isinstance(node, ClassDef) and node.name == "Pending"
            ),
        ]
        if name == "dual":
            contracts.append(
                next(
                    node
                    for node in syntax.body
                    if isinstance(node, ClassDef) and node.name == "OrderRow"
                )
            )
        reports[name] = {
            "sha256": sha256(source.encode()).hexdigest(),
            "lines": len(source.splitlines()),
            "lint": loads(lint.stdout),
            "order_field_counts": [
                sum(
                    isinstance(node, AnnAssign)
                    and isinstance(node.target, Name)
                    and not node.target.id.startswith("__")
                    for node in contract.body
                )
                for contract in contracts
            ],
        }
    async with TemporaryDirectory(
        dir=str(directory.parent.parent / ".git/approach-situations")
    ) as temporary:
        declarations = {
            "nested": """from typing import ClassVar
from scratchpad.paired_situations import nested_sqlite as sqlite
class User(sqlite.Row):
    email: sqlite.Col[str] = sqlite.Text()
    class Pending(sqlite.Pending):
        __row__: ClassVar[type[User]]
        email: sqlite.Col[str]
""",
            "dual": """from typing import ClassVar
from scratchpad.paired_situations import dual_sqlite as sqlite
class User(sqlite.Model):
    __row__: ClassVar[type[UserRow]]
    email: sqlite.Col[str] = sqlite.Text()
class UserRow(User, sqlite.Row):
    table_name = "users"
""",
            "body": """from typing import ClassVar
from snekql.sqlite import Col, Fetched, Pending, Text
from scratchpad.class_body_usage.sqlite import Model, ReadType
class User[State=Pending](Model[State]):
    __read_type__: ClassVar[ReadType[User[Fetched]]]
    email: Col[str] = Text()
""",
        }
        for name, source in declarations.items():
            path = Path(temporary) / f"{name}.py"
            await path.write_text(source)
            process = await run_process([*lint_args, str(path)], check=False)
            if process.returncode:
                raise ModelDeclarationError(
                    "Declaration-only consumer needs an import allowance"
                )
            reports[f"{name}_declaration_lint"] = loads(process.stdout)
    schemas = {}
    for name in ("User", "Counter", "Settings", "Post", "Comment", "Order"):
        nested = n.sqlite.scaffold(getattr(n, name))
        body = b.sqlite.scaffold(
            [b.User, b.Post] if name == "Post" else [getattr(b, name)]
        )
        dual = d.sqlite.scaffold(getattr(d, f"{name}Row"))
        if nested != body or nested != dual:
            message = f"Scaffold differs for {name}"
            raise ModelDeclarationError(message)
        schemas[name] = nested
    schemas["Product"] = n.mariadb.scaffold(n.Product)
    if schemas["Product"] != b.mariadb.scaffold([b.Product]) or schemas[
        "Product"
    ] != d.mariadb.scaffold(d.ProductRow):
        raise ModelDeclarationError("Product Scaffold differs")
    pairs = [
        (
            "user-insert",
            n.sqlite.insert(n.User.Pending(email="A")).returning().compile(),
            b.sqlite.insert(b.User(email="A")).returning().compile(),
        ),
        (
            "counter-default",
            n.sqlite.insert(n.pending_counter()).returning().compile(),
            b.sqlite.insert(b.pending_counter()).returning().compile(),
        ),
        (
            "settings-defaults",
            n.sqlite.insert(
                n.Settings.Pending(user_id=1, timezone="UTC", nickname=None)
            )
            .returning()
            .compile(),
            b.sqlite.insert(b.Settings(user_id=1, timezone="UTC", nickname=None))
            .returning()
            .compile(),
        ),
        (
            "order-insert",
            n.sqlite.insert(n.sample_order()).returning().compile(),
            b.sqlite.insert(b.sample_order()).returning().compile(),
        ),
        ("users-select", n.users_query().compile(), b.users_query().compile()),
        (
            "email-projection",
            n.sqlite.select(n.User.email).all().compile(),
            b.sqlite.select(b.User.email).all().compile(),
        ),
        (
            "author-join",
            n.sqlite.select(n.User.email)
            .join(n.Post, on=n.Post.author_id.references(n.User.user_id))
            .all()
            .compile(),
            b.sqlite.select(b.User.email)
            .join(b.Post, on=b.Post.author_id.references(b.User.user_id))
            .all()
            .compile(),
        ),
        (
            "settings-upsert",
            n.sqlite.insert(
                n.Settings.Pending(user_id=1, timezone="UTC", nickname=None)
            )
            .on_conflict(
                n.Settings.user_id,
                action=n.sqlite.DoUpdate(n.Settings.timezone.to_inserted()),
            )
            .returning()
            .compile(),
            b.sqlite.insert(b.Settings(user_id=1, timezone="UTC", nickname=None))
            .on_conflict(
                b.Settings.user_id,
                action=b.sqlite.DoUpdate(b.Settings.timezone.to_inserted()),
            )
            .returning()
            .compile(),
        ),
    ]
    dual_queries = {
        "user-insert": d.sqlite.insert(d.User(email="A")).returning().compile(),
        "counter-default": d.sqlite.insert(d.pending_counter()).returning().compile(),
        "settings-defaults": d.sqlite.insert(
            d.Settings(user_id=1, timezone="UTC", nickname=None)
        )
        .returning()
        .compile(),
        "order-insert": d.sqlite.insert(d.sample_order()).returning().compile(),
        "users-select": d.users_query().compile(),
        "email-projection": d.sqlite.select(d.UserRow.email).all().compile(),
        "author-join": d.sqlite.select(d.UserRow.email)
        .join(d.PostRow, on=d.PostRow.author_id.references(d.UserRow.user_id))
        .all()
        .compile(),
        "settings-upsert": d.sqlite.insert(
            d.Settings(user_id=1, timezone="UTC", nickname=None)
        )
        .on_conflict(
            d.SettingsRow.user_id,
            action=d.sqlite.DoUpdate(d.SettingsRow.timezone.to_inserted()),
        )
        .returning()
        .compile(),
    }
    queries = {}
    for name, nested, body in pairs:
        if nested != body or nested != dual_queries[name]:
            message = f"SQL or ordered parameters differ for {name}"
            raise ModelDeclarationError(message)
        queries[name] = asdict(nested)
    version = await run_process(["mariadbd", "--version"])
    reports.update(
        scaffold=schemas,
        compiled_queries=queries,
        mariadb=version.stdout.decode().strip(),
    )
    await (directory / "evidence.json").write_text(
        dumps(reports, indent=2, default=_json_value) + "\n"
    )
    print(
        "Seven matching scaffolds; eight matching SQL/parameter triples; all three consumers lint without exceptions"
    )


if __name__ == "__main__":
    run(main)
