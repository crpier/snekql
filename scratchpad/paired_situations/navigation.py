"""Bounded definition requests to the installed ty language server."""

import ast
from hashlib import sha256
from importlib.metadata import version
from json import dumps, loads
from pathlib import Path
from subprocess import DEVNULL
from typing import Any
from urllib.parse import unquote, urlparse

from anyio import Path as AsyncPath
from anyio import fail_after, open_process, run
from snekql.errors import ModelDeclarationError


async def main() -> None:
    root = Path(str(await AsyncPath.cwd()))
    document = root / ".git/approach-situations/navigation_usage.py"
    text = "\n".join(
        [
            '"""Compare navigation for the same application usage."""',
            "from scratchpad.paired_situations.nested import Order as RowFirst",
            "from scratchpad.paired_situations.body import Order as InputFirst",
            "from scratchpad.paired_situations.dual import OrderRow as DualRow; from snekql.sqlite import Fetched as __imported_Fetched",
            "",
            "def names(row: RowFirst, original: InputFirst[__imported_Fetched], dual: DualRow) -> tuple[str, str, str]:",
            "    return row.customer_email, original.customer_email, dual.customer_email",
            "",
        ]
    )
    await AsyncPath(document).write_text(text)
    pending = b""
    async with await open_process(
        ["uv", "run", "ty", "server"], stderr=DEVNULL
    ) as process:
        if process.stdin is None or process.stdout is None:
            raise ModelDeclarationError("Language-server pipes are unavailable")
        stdin, stdout = process.stdin, process.stdout

        async def send(message: dict[str, Any]) -> None:
            body = dumps({"jsonrpc": "2.0", **message}).encode()
            await stdin.send(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)

        async def response(identifier: int) -> dict[str, Any]:
            nonlocal pending
            while True:
                while b"\r\n\r\n" not in pending:
                    pending += await stdout.receive()
                header, rest = pending.split(b"\r\n\r\n", 1)
                length = int(
                    next(
                        line.split(b":")[1]
                        for line in header.split(b"\r\n")
                        if line.lower().startswith(b"content-length:")
                    )
                )
                while len(rest) < length:
                    rest += await stdout.receive()
                body, pending = rest[:length], rest[length:]
                message = loads(body)
                if message.get("id") == identifier:
                    return dict(message)

        with fail_after(40):
            await send(
                {
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "processId": None,
                        "rootUri": root.as_uri(),
                        "capabilities": {},
                        "workspaceFolders": [{"uri": root.as_uri(), "name": "snekql"}],
                    },
                }
            )
            initialized = await response(1)
            await send({"method": "initialized", "params": {}})
            await send(
                {
                    "method": "textDocument/didOpen",
                    "params": {
                        "textDocument": {
                            "uri": document.as_uri(),
                            "languageId": "python",
                            "version": 1,
                            "text": text,
                        }
                    },
                }
            )
            results = {}
            requests = [
                ("row_class", 5, "RowFirst"),
                ("body_class", 5, "InputFirst"),
                ("row_attribute", 6, "customer_email"),
                ("body_attribute", 6, "original.customer_email"),
                ("dual_class", 5, "DualRow"),
                ("dual_attribute", 6, "dual.customer_email"),
            ]
            for identifier, (name, line, symbol) in enumerate(requests, 2):
                column = text.splitlines()[line].index(symbol)
                if "." in symbol:
                    column += len(symbol.split(".")[0]) + 1
                await send(
                    {
                        "id": identifier,
                        "method": "textDocument/definition",
                        "params": {
                            "textDocument": {"uri": document.as_uri()},
                            "position": {"line": line, "character": column},
                        },
                    }
                )
                results[name] = await response(identifier)
            await send({"id": 99, "method": "shutdown", "params": None})
            await response(99)
            await send({"method": "exit", "params": None})
            await process.wait()
    for label, message in results.items():
        locations = message.get("result")
        if not locations:
            error_message = f"No definition returned for {label}"
            raise ModelDeclarationError(error_message)
        module = {"row": "nested", "body": "body", "dual": "dual"}[label.split("_")[0]]
        expected = f"scratchpad/paired_situations/{module}.py"
        for location in locations:
            path = Path(unquote(urlparse(location["uri"]).path))
            location["path"] = str(path.relative_to(root))
            if location["path"] != expected:
                error_message = f"Unexpected definition target for {label}"
                raise ModelDeclarationError(error_message)
            source = await AsyncPath(path).read_text()
            location["source"] = source.splitlines()[location["range"]["start"]["line"]]
            location["sha256"] = sha256(source.encode()).hexdigest()
            expected_symbol = (
                "class Order" if label.endswith("class") else "customer_email:"
            )
            if not location["source"].strip().startswith(expected_symbol):
                error_message = f"Unexpected definition symbol for {label}"
                raise ModelDeclarationError(error_message)
            if label.endswith("class"):
                declaration = next(
                    node
                    for node in ast.parse(source).body
                    if isinstance(node, ast.ClassDef)
                    and node.name
                    == ("OrderRow" if label.startswith("dual_") else "Order")
                )
                location["declared_value_fields"] = [
                    node.target.id
                    for node in declaration.body
                    if isinstance(node, ast.AnnAssign)
                    and isinstance(node.target, ast.Name)
                ]
            del location["uri"]
    report = {
        "ty": version("ty"),
        "capability": initialized.get("result", {})
        .get("capabilities", {})
        .get("definitionProvider"),
        "results": results,
    }
    await AsyncPath("scratchpad/paired_situations/navigation.json").write_text(
        dumps(report, indent=2) + "\n"
    )
    print(dumps(report, indent=2))


if __name__ == "__main__":
    run(main)
