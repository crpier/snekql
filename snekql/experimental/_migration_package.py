"""Decode frozen input without ambiguous JSON member selection."""

import json
from collections.abc import Iterator
from typing import Any, Literal

_OLD_FORMAT = 2
_RELAXATION_FORMAT = 4
_INDEX_FORMAT = 5
_DROP_INDEX_FORMAT = 6
_CHECK_FORMAT = 7
_DROP_CHECK_FORMAT = 8
_FORMAT_VERSIONS = {
    _OLD_FORMAT,
    3,
    _RELAXATION_FORMAT,
    _INDEX_FORMAT,
    _DROP_INDEX_FORMAT,
    _CHECK_FORMAT,
    _DROP_CHECK_FORMAT,
}
# Deliberately separate from capability admission: a future format must choose
# its execution interpretation, not acquire today's default by joining that set.
_EPOCH_ONE_FORMATS = frozenset({2, 3, 4, 5, 6, 7, 8})
_MAX_BYTES = 8 * 1024 * 1024
_MAX_DEPTH = 64
_MAX_STRUCTURE = 100_000


def execution_epoch(version: int) -> Literal[1]:
    """The explicitly supported legacy formats have epoch-one execution semantics."""
    if type(version) is not int or version not in _EPOCH_ONE_FORMATS:
        msg = "unsupported execution interpretation; no automatic conversion"
        raise ValueError(msg)
    return 1


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


def _check_structure(text: str, subject: str) -> None:
    """Bound containers before allocation; JSON still owns syntax validation."""
    depth = 0
    units = 0
    for char in _structural_characters(text):
        if char in "[{":
            units += 1
            depth += 1
            if depth > _MAX_DEPTH:
                msg = f"{subject} exceeds nesting limit (64)"
                raise ValueError(msg)
        elif char in "]}":
            depth -= 1
        elif char == ",":
            units += 1
        if units > _MAX_STRUCTURE:
            msg = f"{subject} exceeds structure limit (100000 containers/separators)"
            raise ValueError(msg)


def read_document(text: str, *, subject: str) -> Any:
    """Bound frozen JSON evidence before allocation and reject duplicate members."""
    if len(text) > _MAX_BYTES or len(text.encode("utf-8")) > _MAX_BYTES:
        msg = f"{subject} exceeds UTF-8 byte limit (8 MiB)"
        raise ValueError(msg)
    _check_structure(text, subject)
    return json.loads(text, object_pairs_hook=_unique_object)


def read_package(text: str) -> Any:
    """Decode each object without silently selecting the last repeated member."""
    value = read_document(text, subject="execution package")
    if (
        not isinstance(value, dict)
        or type(value.get("version")) is not int
        or value["version"] not in _FORMAT_VERSIONS
    ):
        msg = "unsupported execution package version; no automatic conversion"
        raise ValueError(msg)
    if "execution_epoch" in value:
        msg = "unsupported explicit execution epoch; formats 2-8 use the legacy epoch-one reader; no automatic conversion"
        raise ValueError(msg)
    execution_epoch(value["version"])
    draft = value.get("draft")
    operations = draft.get("operations") if isinstance(draft, dict) else None
    if isinstance(operations, list) and any(
        isinstance(operation, dict) and "kind" not in operation
        for operation in operations
    ):
        msg = "serialized execution operation requires an explicit kind"
        raise ValueError(msg)
    if (
        value["version"] < _INDEX_FORMAT
        and isinstance(operations, list)
        and any(
            isinstance(op, dict) and op.get("kind") == "create_index"
            for op in operations
        )
    ):
        msg = "index creation operations require execution package version 5"
        raise ValueError(msg)
    if (
        value["version"] < _DROP_INDEX_FORMAT
        and isinstance(operations, list)
        and any(
            isinstance(op, dict) and op.get("kind") == "drop_index" for op in operations
        )
    ):
        msg = "index removal operations require execution package version 6"
        raise ValueError(msg)
    contractions = value.get("contractions")
    if value["version"] < _CHECK_FORMAT and (
        (
            isinstance(operations, list)
            and any(
                isinstance(op, dict) and op.get("kind") == "add_check"
                for op in operations
            )
        )
        or (
            isinstance(contractions, list)
            and any(
                isinstance(change, dict) and "added_checks" in change
                for change in contractions
            )
        )
    ):
        msg = "CHECK addition operations/metadata require execution package version 7"
        raise ValueError(msg)
    if value["version"] < _DROP_CHECK_FORMAT and (
        (
            isinstance(operations, list)
            and any(
                isinstance(op, dict) and op.get("kind") == "drop_check"
                for op in operations
            )
        )
        or (
            isinstance(contractions, list)
            and any(
                isinstance(change, dict) and "removed_checks" in change
                for change in contractions
            )
        )
    ):
        msg = "CHECK removal operations/metadata require execution package version 8"
        raise ValueError(msg)
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
