"""Property-based storage codec tests for MariaDB.

These complement the example-based tests in ``test_storage_codecs.py`` by
asserting the codec invariants across Hypothesis-generated inputs. They exercise
the column descriptors' ``encode``/``decode`` surface directly -- no live server
-- so they stay fast and deterministic. Where MariaDB's contract differs from a
plain round-trip (DATETIME normalizes to UTC at millisecond precision; TEXT and
BLOB are length-bounded), the property encodes that documented behaviour.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, cast

from hypothesis import settings
from hypothesis import strategies as st
from snektest import (
    assert_eq,
    assert_isinstance,
    assert_raises,
    test_hypothesis,
)

from snekql.mariadb import (
    Blob,
    Boolean,
    DateTime,
    Fetched,
    Integer,
    Json,
    Model,
    ModelValidationError,
    Pending,
    Real,
    Text,
    Uuid,
)

BACKEND = "mariadb"

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1
_TEXT_MAX = 255  # VARCHAR(255)
_BLOB_MAX = 65535  # BLOB, 64 KiB - 1


class Scalars[S = Pending](Model[S, "Scalars[Fetched]"]):
    """One column per MariaDB value family under test."""

    number: Scalars.Col[int] = Integer(nullable=False)
    rating: Scalars.Col[float] = Real(nullable=False)
    label: Scalars.Col[str] = Text(nullable=False)
    blob: Scalars.Col[bytes] = Blob(nullable=False)
    flag: Scalars.Col[bool] = Boolean(nullable=False)
    when: Scalars.Col[datetime] = DateTime(nullable=False)
    account_id: Scalars.Col[uuid.UUID] = Uuid(nullable=False)
    data: Scalars.Col[dict[str, Any]] = Json(nullable=False)


_json_text = st.text(st.characters(codec="utf-8"))
_json_leaves = (
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | _json_text
)
_json_values = st.recursive(
    _json_leaves,
    lambda children: (
        st.lists(children, max_size=5)
        | st.dictionaries(_json_text, children, max_size=5)
    ),
    max_leaves=15,
)
_json_objects = st.dictionaries(_json_text, _json_values, max_size=5)

# DATETIME normalizes to UTC, so only aware inputs have a backend-independent
# expectation (a naive datetime would be interpreted in the host's local zone).
# Unlike the SQLite text path, this conversion uses the full offset, so even
# sub-minute (historical LMT) offsets convert to the correct UTC instant.
_offsets = st.integers(min_value=-(24 * 3600 - 1), max_value=24 * 3600 - 1).map(
    lambda seconds: timezone(timedelta(seconds=seconds))
)
_aware_datetimes = st.datetimes(
    min_value=datetime(1900, 1, 1),  # noqa: DTZ001
    max_value=datetime(2200, 1, 1),  # noqa: DTZ001
    timezones=st.just(UTC) | _offsets,
)


def _expected_datetime(value: datetime) -> datetime:
    """MariaDB DATETIME stores UTC at millisecond precision (truncating)."""

    normalized = value.astimezone(UTC)
    milliseconds = (normalized.microsecond // 1000) * 1000
    return normalized.replace(microsecond=milliseconds)


@settings(deadline=None)
@test_hypothesis(st.integers(min_value=_INT64_MIN, max_value=_INT64_MAX), mark="fast")
def integer_in_range_round_trips(value: int) -> None:
    """Every signed 64-bit (BIGINT) integer encodes unchanged and decodes back."""

    encoded = Scalars.number.encode(value, backend=BACKEND)
    assert_eq(encoded, value)
    assert_eq(Scalars.number.decode(encoded, backend=BACKEND), value)


@settings(deadline=None)
@test_hypothesis(
    st.integers(min_value=_INT64_MAX + 1) | st.integers(max_value=_INT64_MIN - 1),
    mark="fast",
)
def integer_out_of_range_is_rejected(value: int) -> None:
    """Values past the signed 64-bit range fail at encode with a domain error."""

    with assert_raises(ModelValidationError):
        _ = Scalars.number.encode(value, backend=BACKEND)


@settings(deadline=None)
@test_hypothesis(st.floats(allow_nan=False, allow_infinity=False), mark="fast")
def finite_real_round_trips(value: float) -> None:
    """Finite floats (DOUBLE) round-trip exactly."""

    encoded = Scalars.rating.encode(value, backend=BACKEND)
    decoded = cast("float", Scalars.rating.decode(encoded, backend=BACKEND))
    assert_eq(math.copysign(1.0, decoded), math.copysign(1.0, value))
    assert_eq(decoded, value)


@settings(deadline=None)
@test_hypothesis(st.sampled_from([math.nan, math.inf, -math.inf]), mark="fast")
def non_finite_real_is_rejected(value: float) -> None:
    """nan / inf / -inf cannot be stored in DOUBLE and are rejected at encode."""

    with assert_raises(ModelValidationError):
        _ = Scalars.rating.encode(value, backend=BACKEND)


@settings(deadline=None)
@test_hypothesis(st.text(st.characters(codec="utf-8"), max_size=_TEXT_MAX), mark="fast")
def text_within_limit_round_trips(value: str) -> None:
    """Strings up to VARCHAR(255) round-trip unchanged."""

    encoded = Scalars.label.encode(value, backend=BACKEND)
    assert_eq(Scalars.label.decode(encoded, backend=BACKEND), value)


@settings(deadline=None)
@test_hypothesis(
    st.text(st.characters(codec="utf-8"), min_size=_TEXT_MAX + 1, max_size=320),
    mark="fast",
)
def text_over_limit_is_rejected(value: str) -> None:
    """Strings longer than VARCHAR(255) are rejected rather than truncated."""

    with assert_raises(ModelValidationError):
        _ = Scalars.label.encode(value, backend=BACKEND)


@settings(deadline=None, max_examples=25)
@test_hypothesis(st.binary(max_size=_BLOB_MAX), mark="fast")
def blob_within_limit_round_trips(value: bytes) -> None:
    """Byte strings up to the BLOB ceiling round-trip unchanged."""

    encoded = Scalars.blob.encode(value, backend=BACKEND)
    assert_eq(Scalars.blob.decode(encoded, backend=BACKEND), value)


# The oversized value is built from a single fill byte rather than generated
# wholesale, so Hypothesis never has to materialize 64 KiB of random bytes.
@settings(deadline=None)
@test_hypothesis(
    st.binary(min_size=1, max_size=1),
    st.integers(min_value=1, max_value=64),
    mark="fast",
)
def blob_over_limit_is_rejected(fill: bytes, overflow: int) -> None:
    """Byte strings past the BLOB ceiling are rejected rather than truncated."""

    value = fill * (_BLOB_MAX + overflow)
    with assert_raises(ModelValidationError):
        _ = Scalars.blob.encode(value, backend=BACKEND)


@settings(deadline=None)
@test_hypothesis(st.booleans(), mark="fast")
def boolean_round_trips_through_tinyint(value: bool) -> None:  # noqa: FBT001
    """Boolean encodes to 1/0 and decodes the driver tinyint back to a real bool."""

    encoded = Scalars.flag.encode(value, backend=BACKEND)
    assert_eq(encoded, int(value))
    decoded = Scalars.flag.decode(int(value), backend=BACKEND)
    assert_isinstance(decoded, bool)
    assert_eq(decoded, value)


@settings(deadline=None)
@test_hypothesis(st.integers().filter(lambda n: n not in (0, 1)), mark="fast")
def boolean_decode_rejects_non_binary_integers(value: int) -> None:
    """A boolean column decodes only 0/1; any other driver integer is rejected."""

    with assert_raises(ModelValidationError):
        _ = Scalars.flag.decode(value, backend=BACKEND)


@settings(deadline=None)
@test_hypothesis(_aware_datetimes, mark="fast")
def datetime_normalizes_to_utc_milliseconds(value: datetime) -> None:
    """An aware datetime encodes to its UTC instant at millisecond precision and
    decodes back to that normalized value."""

    encoded = Scalars.when.encode(value, backend=BACKEND)
    decoded = Scalars.when.decode(encoded, backend=BACKEND)
    assert_eq(decoded, _expected_datetime(value))


@settings(deadline=None)
@test_hypothesis(st.uuids(), mark="fast")
def uuid_round_trips_as_text(value: uuid.UUID) -> None:
    """The native Uuid type round-trips through its string form on the wire."""

    encoded = Scalars.account_id.encode(value, backend=BACKEND)
    assert_eq(encoded, str(value))
    assert_eq(Scalars.account_id.decode(encoded, backend=BACKEND), value)


@settings(deadline=None)
@test_hypothesis(_json_objects, mark="fast")
def json_round_trips_arbitrary_payloads(value: dict[str, Any]) -> None:
    """The JSON wire codec round-trips arbitrarily nested objects/arrays, and
    also decodes the ``bytes`` the driver hands back for JSON columns."""

    encoded = Scalars.data.encode(value, backend=BACKEND)
    assert_isinstance(encoded, str)
    assert_eq(Scalars.data.decode(encoded, backend=BACKEND), value)
    # The driver hands JSON columns back as bytes; the codec decodes those too.
    encoded_bytes = cast("str", encoded).encode()
    assert_eq(Scalars.data.decode(encoded_bytes, backend=BACKEND), value)
