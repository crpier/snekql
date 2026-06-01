"""MariaDB backend namespace for snekql."""

from __future__ import annotations

from snekql.indexes import Index
from snekql.mariadb.config import Config
from snekql.mariadb.model import Model, ModelMeta
from snekql.mariadb.storage import (
    Blob,
    Boolean,
    CurrentTimestamp,
    DateTime,
    Integer,
    Json,
    Real,
    Text,
)
from snekql.model import Col, Fetched, GenCol, Pending, Table
from snekql.storage import MISSING, Attr, Missing, SchemaPolicy

__all__ = [
    "MISSING",
    "Attr",
    "Blob",
    "Boolean",
    "Col",
    "Config",
    "CurrentTimestamp",
    "DateTime",
    "Fetched",
    "GenCol",
    "Index",
    "Integer",
    "Json",
    "Missing",
    "Model",
    "ModelMeta",
    "Pending",
    "Real",
    "SchemaPolicy",
    "Table",
    "Text",
]
