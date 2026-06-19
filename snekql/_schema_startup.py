"""Backend-neutral schema startup flow shared by Backend Runtime Adapters."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from snekql._schema_plan import (
    build_schema_plan,
)
from snekql._schema_plan import (
    validate_schema_policy as validate_planned_schema_policy,
)
from snekql._schema_shape import diff_table_shapes
from snekql.errors import SchemaVerificationError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractAsyncContextManager

    from snekql._schema_plan import PlannedModel
    from snekql._schema_shape import TableShape
    from snekql.indexes import NormalizedIndex
    from snekql.model import Table
    from snekql.storage import SchemaPolicy

logger = logging.getLogger(__name__)


class SchemaBackend(Protocol):
    """Backend seam for schema DDL execution and live-schema inspection.

    The startup flow — verify-or-create per table, semantic Schema Drift
    reporting under the active Schema Policy — lives in this module. Backends
    answer only with the shape a model expects, the shape a live table actually
    has, and how to create what is missing; the shared flow diffs the two and
    names each divergence.
    """

    def startup_transaction(self) -> AbstractAsyncContextManager[None]: ...

    def expected_shape(self, planned_model: PlannedModel) -> TableShape: ...

    async def inspect_shape(self, planned_model: PlannedModel) -> TableShape | None: ...

    async def create_table(self, planned_model: PlannedModel) -> None: ...

    async def create_index(self, table_name: str, index: NormalizedIndex) -> str: ...


def validate_schema_models(models: Sequence[type[Table[Any]]]) -> None:
    """Reject duplicate resolved table names before schema startup."""

    _ = build_schema_plan(models)


def validate_schema_policy(schema_policy: SchemaPolicy) -> None:
    """Reject unsupported schema policy values."""

    validate_planned_schema_policy(schema_policy)


def _report_schema_drift(
    schema_policy: SchemaPolicy,
    table_name: str,
    issues: Sequence[str],
) -> None:
    detail = "; ".join(issues)
    message = f"schema drift detected for table {table_name!r}: {detail}"
    if schema_policy == "strict":
        raise SchemaVerificationError(message)
    logger.warning("%s", message)


async def _create_model_schema(
    backend: SchemaBackend,
    planned_model: PlannedModel,
) -> None:
    await backend.create_table(planned_model)
    logger.debug("schema table %r created", planned_model.table_name)
    for index in planned_model.indexes:
        sql = await backend.create_index(planned_model.table_name, index)
        logger.debug("schema index created on %r: %s", planned_model.table_name, sql)


async def _verify_model_schema(
    backend: SchemaBackend,
    planned_model: PlannedModel,
    actual_shape: TableShape,
    schema_policy: SchemaPolicy,
) -> None:
    expected_shape = backend.expected_shape(planned_model)
    issues = diff_table_shapes(expected_shape, actual_shape)
    if issues:
        _report_schema_drift(schema_policy, planned_model.table_name, issues)
        return
    logger.debug("schema table and indexes for %r verified", planned_model.table_name)


async def initialize_schema(
    backend: SchemaBackend,
    models: Sequence[type[Table[Any]]],
    schema_policy: SchemaPolicy,
    *,
    create_missing: bool = True,
) -> None:
    """Create or verify all configured tables through one schema backend.

    When `create_missing` is False, Migrations are the sole schema-creation
    authority: a missing table is reported as Schema Drift instead of being
    created, so the models stay the enforced contract the migration list must
    converge to.
    """

    validate_schema_policy(schema_policy)
    plan = build_schema_plan(models)
    if not plan.models:
        return
    logger.debug("schema startup started for %d model(s)", len(plan.models))
    async with backend.startup_transaction():
        for planned_model in plan.models:
            actual_shape = await backend.inspect_shape(planned_model)
            if actual_shape is None:
                if not create_missing:
                    _report_schema_drift(
                        schema_policy,
                        planned_model.table_name,
                        ("table is missing from the database",),
                    )
                    continue
                await _create_model_schema(backend, planned_model)
                continue
            await _verify_model_schema(
                backend, planned_model, actual_shape, schema_policy
            )
    logger.debug("schema startup completed for %d model(s)", len(plan.models))
