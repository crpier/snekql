"""Backend-neutral schema startup flow shared by Backend Runtime Adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from snekql._schema_plan import (
    build_schema_plan,
)
from snekql._schema_plan import (
    validate_schema_policy as validate_planned_schema_policy,
)
from snekql.errors import SchemaVerificationError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractAsyncContextManager

    from snekql._schema_plan import PlannedModel
    from snekql.indexes import NormalizedIndex
    from snekql.model import Table
    from snekql.storage import SchemaPolicy
    from snekql.structured_logging import ResolvedStructuredLogger


class SchemaBackend(Protocol):
    """Backend seam for schema DDL execution and live-schema inspection.

    The startup flow — verify-or-create per table, Schema Drift reporting
    under the active Schema Policy — lives in this module; backends only
    answer what exists, whether it matches, and how to create what is
    missing.
    """

    def startup_transaction(self) -> AbstractAsyncContextManager[None]: ...

    async def table_exists(self, table_name: str) -> bool: ...

    async def table_matches(self, planned_model: PlannedModel) -> bool: ...

    async def indexes_match(self, planned_model: PlannedModel) -> bool: ...

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
    logger: ResolvedStructuredLogger,
) -> None:
    message = f"schema drift detected for table {table_name!r}"
    if schema_policy == "strict":
        raise SchemaVerificationError(message)
    logger.warning(
        "schema drift detected",
        table_name=table_name,
    )


async def _create_model_schema(
    backend: SchemaBackend,
    planned_model: PlannedModel,
    logger: ResolvedStructuredLogger,
) -> None:
    await backend.create_table(planned_model)
    logger.debug("schema table created", table_name=planned_model.table_name)
    for index in planned_model.indexes:
        sql = await backend.create_index(planned_model.table_name, index)
        logger.debug(
            "schema index created",
            table_name=planned_model.table_name,
            sql=sql,
        )


async def _verify_model_schema(
    backend: SchemaBackend,
    planned_model: PlannedModel,
    schema_policy: SchemaPolicy,
    logger: ResolvedStructuredLogger,
) -> None:
    if not await backend.table_matches(planned_model):
        _report_schema_drift(schema_policy, planned_model.table_name, logger=logger)
        return
    logger.debug("schema table verified", table_name=planned_model.table_name)
    if not await backend.indexes_match(planned_model):
        _report_schema_drift(schema_policy, planned_model.table_name, logger=logger)
        return
    logger.debug("schema indexes verified", table_name=planned_model.table_name)


async def initialize_schema(
    backend: SchemaBackend,
    models: Sequence[type[Table[Any]]],
    schema_policy: SchemaPolicy,
    *,
    logger: ResolvedStructuredLogger,
) -> None:
    """Create or verify all configured tables through one schema backend."""

    validate_schema_policy(schema_policy)
    plan = build_schema_plan(models)
    if not plan.models:
        return
    logger.debug("schema startup started", model_count=len(plan.models))
    async with backend.startup_transaction():
        for planned_model in plan.models:
            if not await backend.table_exists(planned_model.table_name):
                await _create_model_schema(backend, planned_model, logger)
                continue
            await _verify_model_schema(backend, planned_model, schema_policy, logger)
    logger.debug("schema startup completed", model_count=len(plan.models))
