"""Backend Dialect seam used by shared schema DDL/shape compilation.

Mirrors :mod:`snekql._query_dialect`: the schema DDL and expected-shape
compilation lives once in :mod:`snekql._schema_compile`, and each backend
supplies only the parts that genuinely diverge. Column definitions and expected
column shapes stay per-backend callbacks because their divergence (clause order,
NOT NULL semantics, keyword spelling, storage-type rendering, collation) is not
expressible as flat facts; everything around them -- foreign-key constraints,
index SQL, the CREATE TABLE skeleton, and the table-shape skeleton -- is shared.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from snekql._schema_plan import PlannedColumn
    from snekql._schema_shape import ColumnShape, IndexShape
    from snekql.indexes import NormalizedIndex


@dataclass(frozen=True)
class SchemaDialect:
    """Dialect seam for compiling a schema plan into backend DDL and shape."""

    quote_identifier: Callable[[str], str]
    compile_column_definition: Callable[[PlannedColumn], str]
    expected_column_shape: Callable[[PlannedColumn], ColumnShape]
    expected_index_shape: Callable[[NormalizedIndex], IndexShape]
    normalize_foreign_key_action: Callable[[str | None], str]
    table_suffix: str
    verifies_foreign_keys: bool
