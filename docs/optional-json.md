# Optional JSON fields

Both `Col[Json[T] | None]` and `Col[Json[T | None]]` accept decoded Python
payloads and `None`. Use SQLite `Text()`, MariaDB `Text()`, or MariaDB native
`Json()` storage. Construction, assignment and validated reads use the logical
payload type, not Pydantic's encoded-JSON input convention.

The field-level Json marker selects the wire codec. Other `Annotated` metadata,
including constraints, validators and serializers, keeps its original order.
Only wrappers around that field marker are traversed. Nested payload annotations
such as `Json[list[Json[int]]]` retain Pydantic's nested JSON parsing semantics.
Type-alias resolution beyond the existing resolver is not expanded here.

A mixed field union such as `Json[list[int]] | str` cannot select a consistent
wire convention and raises `ModelDeclarationError` when resolved. The same
restriction applies to multiple marked alternatives. Put one marker around the
entire payload union instead: `Json[list[int] | str]`. A native MariaDB `Json()`
column can also use a plain logical payload union without a Pydantic Json marker.

## SQL NULL and JSON null

Python `None` writes SQL NULL, including with `Json[T | None]`. The API does not
use that spelling to request the JSON text `null`. Existing JSON text `null` and
SQL NULL both decode to Python `None` when the logical payload permits it, but
remain different stored values: `is_null()` matches SQL NULL only. Reads do not
rewrite either representation.

## Compatibility

Pass decoded values such as `[1, 2]`, not strings containing encoded JSON, to
optional JSON fields. Field metadata now remains effective rather than being
lost during marker stripping. Audit historical rows and validators if existing
code depended on dropped constraints or serializers. `validate=False` still
parses JSON without logical validation; it does not accept malformed JSON wire
text. No data or schema migration runs automatically.
