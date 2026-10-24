"""Decode frozen input without ambiguous JSON member selection."""

import json
from collections.abc import Iterator
from typing import Any

_OLD_FORMAT = 2
_RELAXATION_FORMAT = 4
_FORMAT_VERSIONS = {_OLD_FORMAT, 3, _RELAXATION_FORMAT}
_MAX_BYTES = 8 * 1024 * 1024
_MAX_DEPTH = 64
_MAX_STRUCTURE = 100_000


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            msg = "duplicate JSON object member"
            raise ValueError(msg)
        result[key] = value
    return result


def _structural_characters(text: str) -> Iterator[str]:
    """Skip quoted content, including escaped backslashes and quotes."""
    quoted = False
    escaped = False
    for char in text:
        if quoted:
            if char == '"' and not escaped:
                quoted = False
            escaped = char == "\\" and not escaped
            continue
        quoted = char == '"'
        if not quoted:
            yield char


def _check_structure(text: str) -> None:
    """Bound containers before allocation; JSON still owns syntax validation."""
    depth = 0
    units = 0
    for char in _structural_characters(text):
        if char in "[{":
            units += 1
            depth += 1
            if depth > _MAX_DEPTH:
                msg = "execution package exceeds nesting limit (64)"
                raise ValueError(msg)
        elif char in "]}":
            depth -= 1
        elif char == ",":
            units += 1
        if units > _MAX_STRUCTURE:
            msg = "execution package exceeds structure limit (100000 containers/separators)"
            raise ValueError(msg)


def read_package(text: str) -> Any:
    """Decode each object without silently selecting the last repeated member."""
    if len(text) > _MAX_BYTES or len(text.encode("utf-8")) > _MAX_BYTES:
        msg = "execution package exceeds UTF-8 byte limit (8 MiB)"
        raise ValueError(msg)
    _check_structure(text)
    value = json.loads(text, object_pairs_hook=_unique_object)
    if (
        not isinstance(value, dict)
        or type(value.get("version")) is not int
        or value["version"] not in _FORMAT_VERSIONS
    ):
        msg = "unsupported execution package version; no automatic conversion"
        raise ValueError(msg)
    draft = value.get("draft")
    operations = draft.get("operations") if isinstance(draft, dict) else None
    if isinstance(operations, list) and any(
        isinstance(operation, dict) and "kind" not in operation
        for operation in operations
    ):
        msg = "serialized execution operation requires an explicit kind"
        raise ValueError(msg)
    contractions = value.get("contractions")
    if value["version"] == _OLD_FORMAT and (
        (
            isinstance(operations, list)
            and any(
                isinstance(op, dict) and op.get("kind") == "change_default"
                for op in operations
            )
        )
        or (
            isinstance(contractions, list)
            and any(
                isinstance(change, dict) and "defaults" in change
                for change in contractions
            )
        )
    ):
        msg = (
            "default transition operations/metadata require execution package version 3"
        )
        raise ValueError(msg)
    if value["version"] < _RELAXATION_FORMAT and (
        (
            isinstance(operations, list)
            and any(
                isinstance(op, dict) and op.get("kind") == "allow_null"
                for op in operations
            )
        )
        or (
            isinstance(contractions, list)
            and any(
                isinstance(change, dict) and "relaxed" in change
                for change in contractions
            )
        )
    ):
        msg = "nullability relaxation operations/metadata require execution package version 4"
        raise ValueError(msg)
    return value
