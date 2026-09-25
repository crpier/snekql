"""Explicit native bridges for verbs absent from the nested research adapter.

These strings are NOT statically checked field assignments. Keep this limitation
visible in the comparison; do not mistake these bridges for a proposed interface.
"""

from collections.abc import Mapping

from snekql import sqlite as native

from scratchpad.dual_finalization.interface import Schema
from scratchpad.paired_situations import nested_sqlite as sqlite


async def native_update(
    transaction: sqlite.Transaction,
    row: type[sqlite.Row],
    *,
    values: Mapping[str, object],
    key: tuple[str, object] | None = None,
) -> None:
    model = Schema(row).native(row)
    query = native.update(model).set(
        *(getattr(model, name).to(value) for name, value in values.items())
    )
    query = (
        query.all() if key is None else query.where(getattr(model, key[0]).eq(key[1]))
    )
    await transaction.native.execute(query)


async def native_delete(
    transaction: sqlite.Transaction, row: type[sqlite.Row], *, key: tuple[str, object]
) -> None:
    model = Schema(row).native(row)
    await transaction.native.execute(
        native.delete(model).where(getattr(model, key[0]).eq(key[1]))
    )
