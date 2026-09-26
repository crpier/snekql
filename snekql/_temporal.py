"""Concrete temporal meanings, independent of physical column storage."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from json import JSONDecodeError, dumps, loads
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import GetCoreSchemaHandler
from pydantic_core import PydanticSerializationUnexpectedValue, core_schema

from snekql.errors import DatetimeError, ZonedDatetimeError

_ZONED_DATETIME_WIRE_VERSION = 1


def _temporal_schema[ValueT](
    value_type: type[ValueT],
    decode: Callable[[str], ValueT],
    encode: Callable[[ValueT], str],
) -> core_schema.CoreSchema:
    """Separate nominal Python input from canonical wire decoding and serialization."""
    wire = core_schema.chain_schema(
        [
            core_schema.str_schema(),
            core_schema.no_info_plain_validator_function(decode),
        ]
    )
    instance = core_schema.is_instance_schema(value_type)
    return core_schema.json_or_python_schema(
        json_schema=wire,
        python_schema=core_schema.lax_or_strict_schema(
            lax_schema=core_schema.union_schema([instance, wire]),
            strict_schema=instance,
        ),
        serialization=core_schema.plain_serializer_function_ser_schema(
            encode, return_schema=core_schema.str_schema(), when_used="json"
        ),
    )


@dataclass(frozen=True, slots=True, order=True)
class UtcDatetime:
    """An immutable UTC instant retaining all microseconds.

    >>> UtcDatetime(datetime(2026, 1, 1, tzinfo=UTC)).datetime.tzinfo is UTC
    True
    """

    datetime: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.datetime, datetime) or self.datetime.utcoffset() is None:
            msg = "UtcDatetime requires an aware datetime"
            raise DatetimeError(msg)
        try:
            instant = self.datetime.astimezone(UTC).replace(fold=0)
        except (OverflowError, ValueError) as e:
            msg = "UtcDatetime requires a representable UTC instant"
            raise DatetimeError(msg) from e
        object.__setattr__(self, "datetime", instant)

    @classmethod
    def __get_pydantic_core_schema__(
        cls, _source_type: object, _handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        """Keep Python construction nominal and decode canonical text explicitly."""
        return _temporal_schema(cls, cls._from_wire, cls._serialize)

    @staticmethod
    def _serialize(value: UtcDatetime) -> str:
        if not isinstance(value, UtcDatetime):
            msg = "expected UtcDatetime for temporal serialization"
            raise PydanticSerializationUnexpectedValue(msg)
        return (
            value.datetime.isoformat(timespec="microseconds").removesuffix("+00:00")
            + "Z"
        )

    @classmethod
    def _from_wire(cls, value: str) -> UtcDatetime:
        try:
            instant = cls(datetime.fromisoformat(value))
        except (ValueError, OverflowError) as e:
            msg = "invalid UtcDatetime canonical text"
            raise DatetimeError(msg) from e
        if cls._serialize(instant) != value:
            msg = "noncanonical UtcDatetime text; migrate the stored representation"
            raise DatetimeError(msg)
        return instant


@dataclass(frozen=True, slots=True, order=True)
class LocalDatetime:
    """An immutable timezone-free civil datetime, not an absolute instant.

    >>> LocalDatetime(datetime(2026, 1, 1, 9)).datetime.hour
    9
    """

    datetime: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.datetime, datetime)
            or self.datetime.tzinfo is not None
            or self.datetime.fold != 0
        ):
            msg = "LocalDatetime requires timezone-free civil fields without a fold"
            raise DatetimeError(msg)

    @classmethod
    def __get_pydantic_core_schema__(
        cls, _source_type: object, _handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        """Keep Python construction nominal and decode canonical text explicitly."""
        return _temporal_schema(cls, cls._from_wire, cls._serialize)

    @staticmethod
    def _serialize(value: LocalDatetime) -> str:
        if not isinstance(value, LocalDatetime):
            msg = "expected LocalDatetime for temporal serialization"
            raise PydanticSerializationUnexpectedValue(msg)
        return value.datetime.isoformat(timespec="microseconds")

    @classmethod
    def _from_wire(cls, value: str) -> LocalDatetime:
        try:
            instant = cls(datetime.fromisoformat(value))
        except (ValueError, OverflowError) as e:
            msg = "invalid LocalDatetime canonical text"
            raise DatetimeError(msg) from e
        if cls._serialize(instant) != value:
            msg = "noncanonical LocalDatetime text; migrate the stored representation"
            raise DatetimeError(msg)
        return instant


def _zoned_timezone_identity(value: datetime) -> tuple[str, str | timedelta | None]:
    """Identify a named IANA zone separately from a fixed UTC offset."""

    if isinstance(value.tzinfo, ZoneInfo):
        return ("iana", value.tzinfo.key)
    return ("offset", value.utcoffset())


@dataclass(frozen=True, slots=True, eq=False)
class ZonedDatetime:
    """A datetime paired with its persistent timezone identity.

    >>> from datetime import datetime
    >>> from zoneinfo import ZoneInfo
    >>> value = ZonedDatetime(
    ...     datetime(2026, 7, 1, 8, tzinfo=ZoneInfo("America/New_York"))
    ... )
    >>> value.datetime.tzinfo == ZoneInfo("America/New_York")
    True
    """

    datetime: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.datetime, datetime) or self.datetime.utcoffset() is None:
            msg = "ZonedDatetime requires an aware datetime"
            raise ZonedDatetimeError(msg)
        if not isinstance(self.datetime.tzinfo, ZoneInfo | timezone):
            msg = "ZonedDatetime requires an IANA zone or fixed UTC offset"
            raise ZonedDatetimeError(msg)
        try:
            instant = self.datetime.astimezone(UTC)
        except OverflowError as e:
            msg = "ZonedDatetime requires an instant within the UTC datetime range"
            raise ZonedDatetimeError(msg) from e
        if isinstance(self.datetime.tzinfo, ZoneInfo):
            if not self.datetime.tzinfo.key:
                msg = "ZonedDatetime requires an IANA zone with a persistent key"
                raise ZonedDatetimeError(msg)
            reconstructed = instant.astimezone(self.datetime.tzinfo)
            if (
                reconstructed.replace(tzinfo=None) != self.datetime.replace(tzinfo=None)
                or reconstructed.fold != self.datetime.fold
            ):
                msg = "ZonedDatetime requires an existing IANA civil time and fold"
                raise ZonedDatetimeError(msg)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ZonedDatetime):
            return False
        return self.datetime.astimezone(UTC) == other.datetime.astimezone(
            UTC
        ) and _zoned_timezone_identity(self.datetime) == _zoned_timezone_identity(
            other.datetime
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.datetime.astimezone(UTC),
                _zoned_timezone_identity(self.datetime),
            )
        )

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: object,
        _handler: GetCoreSchemaHandler,
    ) -> core_schema.CoreSchema:
        """Validate instances and decode their canonical text wire form."""

        return _temporal_schema(cls, cls._from_wire, cls._serialize)

    @staticmethod
    def _serialize(value: ZonedDatetime) -> str:
        if not isinstance(value, ZonedDatetime):
            msg = "expected ZonedDatetime for temporal serialization"
            raise PydanticSerializationUnexpectedValue(msg)
        instant = value.datetime.astimezone(UTC).isoformat(timespec="microseconds")
        instant = instant.removesuffix("+00:00") + "Z"
        timezone_info = value.datetime.tzinfo
        if isinstance(timezone_info, ZoneInfo):
            timezone_kind = "iana"
            timezone_value: str | int = timezone_info.key
        else:
            offset = value.datetime.utcoffset()
            if offset is None:
                msg = "ZonedDatetime lost its fixed UTC offset"
                raise ZonedDatetimeError(msg)
            timezone_kind = "offset"
            timezone_value = offset // timedelta(microseconds=1)
        return dumps(
            [_ZONED_DATETIME_WIRE_VERSION, instant, timezone_kind, timezone_value],
            ensure_ascii=True,
            separators=(",", ":"),
        )

    @classmethod
    def _from_wire(cls, value: str) -> ZonedDatetime:
        try:
            payload = loads(value)
            if not isinstance(payload, list):
                raise TypeError  # noqa: TRY301
            version, instant_text, timezone_kind, timezone_value = payload
            if version != _ZONED_DATETIME_WIRE_VERSION:
                raise ValueError  # noqa: TRY301
            if not isinstance(instant_text, str) or not instant_text.endswith("Z"):
                raise ValueError  # noqa: TRY301
            instant = datetime.fromisoformat(instant_text.removesuffix("Z") + "+00:00")
            if timezone_kind == "iana" and isinstance(timezone_value, str):
                timezone_info = ZoneInfo(timezone_value)
            elif timezone_kind == "offset" and type(timezone_value) is int:
                timezone_info = timezone(timedelta(microseconds=timezone_value))
            else:
                raise ValueError  # noqa: TRY301
            result = cls(instant.astimezone(timezone_info))
            if cls._serialize(result) != value:
                raise ValueError  # noqa: TRY301
        except (
            JSONDecodeError,
            OverflowError,
            TypeError,
            ValueError,
            ZoneInfoNotFoundError,
        ) as error:
            msg = "invalid ZonedDatetime canonical text"
            raise ValueError(msg) from error
        return result
