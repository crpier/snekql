"""Historical source reconstructs only a bounded default primitive, not any codec."""

import keyword

from snekql.errors import SchemaError
from snekql.experimental._migration_mariadb import mariadb_construction_storage_matches
from snekql.experimental._migration_storage import _sqlite_storage
from snekql.experimental.migrations import Backend, ColumnState, PackageError


def historical_primitive_matches(column: ColumnState, backend: Backend) -> bool:
    """Check the proposed default primitive against its recorded physical definition.

    The storage hint proposes a constructor; it does not prove a codec. Do not infer
    native datetime/decimal/JSON or parameterized codecs from a coarse storage family.
    """
    sqlite_types = {
        "INTEGER": "INTEGER",
        "TEXT": "TEXT",
        "REAL": "REAL",
        "BLOB": "BLOB",
    }
    native_types = {
        "INTEGER": "BIGINT",
        "TEXT": "VARCHAR(255)",
        "REAL": "DOUBLE",
        "BLOB": "BLOB",
    }
    if column.storage not in sqlite_types:
        return False
    try:
        if backend == "sqlite":
            return (
                _sqlite_storage(column.definition)
                == sqlite_types[column.storage].lower()
            )
        return mariadb_construction_storage_matches(
            column.definition, f"`historical` {native_types[column.storage]}"
        )
    except PackageError, SchemaError:
        return False


def historical_annotation(source: str | None) -> str | None:
    """Emit only literal builtin scalar names/unions, never evaluate annotations."""
    if source is None:
        return None
    parts = tuple(dict.fromkeys(part.strip() for part in source.split("|")))
    if any(
        part not in {"int", "str", "float", "bytes", "bool", "None"} for part in parts
    ):
        return None
    return " | ".join(parts)


def historical_field_name(name: str, backend: Backend) -> bool:
    """Keep generated framework/type names unshadowed; exotic SQL names need adapters."""
    return (
        name.isascii()
        and name.isidentifier()
        and not keyword.iskeyword(name)
        and not name.startswith("__")
        and name
        not in {
            backend,
            "Historical",
            "ClassVar",
            "int",
            "str",
            "float",
            "bytes",
            "bool",
        }
    )
